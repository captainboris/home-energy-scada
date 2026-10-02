"""systemd entry point for the persistent fast-telemetry collector."""

from __future__ import annotations

import asyncio
import json
import random
import re
import signal
import time

import aiohttp

from . import VERSION
from .config import ConfigError, Settings
from .dedupe import RecentTimestamps
from .dynamodb_writer import DynamoWriter
from .foxess_auth import AuthError, FoxAuth, ProtocolError
from .foxess_ws import connect
from .health import Health, log_event
from .parser import parse_frame


def safe_error(exc: Exception) -> str:
    text = str(exc)[:300]
    text = re.sub(r"(?i)(token|password|signature)=?[^&\s]+", r"\1=[REDACTED]", text)
    text = re.sub(r"([?&](?:token|signature)=)[^&\s]+", r"\1[REDACTED]", text)
    return text


class Service:
    def __init__(self, settings: Settings, health: Health | None = None,
                 writer: DynamoWriter | None = None, clock=time.monotonic):
        self.settings = settings
        self.health = health or Health()
        self.clock = clock
        self.dedupe = RecentTimestamps(settings.dedupe_capacity)
        self.writer = writer or DynamoWriter(settings, self.health)
        self.stop_event = asyncio.Event()
        self.token: str | None = None
        self.plant_id: str | None = None
        self.token_at = 0.0

    def request_stop(self) -> None:
        self.stop_event.set()

    async def authenticate(self, session, auth: FoxAuth, force: bool = False) -> None:
        if not force and self.token and self.plant_id and self.clock() - self.token_at < 1800:
            return
        self.token = await auth.login(session)
        self.plant_id = await auth.plant_id(session, self.token)
        self.token_at = self.clock()
        self.health.auth_refresh_count += 1
        log_event("ws_auth_refreshed", auth_refresh_count=self.health.auth_refresh_count)

    async def consume_connection(self, session) -> bool:
        """Return True after a useful LIVE session so backoff can reset."""
        assert self.token and self.plant_id
        self.health.transition("CONNECTING")
        socket = await connect(session, self.plant_id, self.token)
        session_started = self.clock()
        last_fresh = session_started
        last_probe = session_started
        became_live = False
        self.health.connected = True
        self.health.transition("RECOVERING", "connected_waiting_for_fresh_sample")
        log_event("ws_connected")
        await socket.send_str("getdata")
        try:
            while not self.stop_event.is_set():
                now = self.clock()
                fresh_age = now - last_fresh
                if fresh_age >= self.settings.reconnect_after_seconds:
                    self.health.transition("RECOVERING", "fresh_sample_timeout")
                    log_event("ws_reconnect_requested", reason="fresh_sample_timeout",
                              fresh_age_seconds=round(fresh_age, 1))
                    break
                if now - session_started >= self.settings.max_session_seconds:
                    self.health.transition("RECOVERING", "planned_session_refresh")
                    log_event("ws_reconnect_requested", reason="planned_session_refresh")
                    break
                if fresh_age >= self.settings.stale_after_seconds:
                    self.health.transition("STALE", "no_new_source_timestamp")
                    if now - last_probe >= self.settings.recovery_probe_seconds:
                        await socket.send_str("getdata")
                        last_probe = now
                        log_event("ws_recovery_probe", fresh_age_seconds=round(fresh_age, 1))
                try:
                    message = await asyncio.wait_for(socket.receive(), timeout=5.0)
                except asyncio.TimeoutError:
                    continue
                received_ms = int(time.time() * 1000)
                if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                    log_event("ws_disconnected", reason="server_close")
                    break
                if message.type == aiohttp.WSMsgType.ERROR:
                    log_event("ws_disconnected", reason="socket_error")
                    break
                if message.type != aiohttp.WSMsgType.TEXT:
                    continue
                self.health.frame(received_ms)
                try:
                    frame = json.loads(message.data)
                except (TypeError, json.JSONDecodeError):
                    self.health.rejected("invalid_json")
                    continue
                parsed = parse_frame(frame, received_ms, self.settings)
                if parsed.sample is None:
                    self.health.rejected(parsed.reason, parsed.time_diff)
                    continue
                sample = parsed.sample
                if not self.dedupe.add(sample.identity()):
                    self.health.duplicate()
                    continue
                last_fresh = self.clock()
                self.health.fresh(
                    sample.source_epoch_ms, received_ms, sample.time_diff_seconds
                )
                if not became_live:
                    became_live = True
                    self.health.transition("LIVE", "fresh_samples_resumed")
                if self.settings.debug_frames:
                    log_event(
                        "ws_sample_debug", source_epoch_ms=sample.source_epoch_ms,
                        time_diff=sample.time_diff_seconds,
                        pv_power_kw=sample.pv_power_kw,
                        load_power_kw=sample.load_power_kw,
                        grid_power_kw=sample.grid_power_kw,
                        battery_power_kw=sample.battery_power_kw,
                        battery_soc_pct=sample.battery_soc_pct,
                    )
                self.writer.enqueue(sample)
        finally:
            self.health.connected = False
            await socket.close()
        return became_live

    async def run(self) -> None:
        timeout = aiohttp.ClientTimeout(
            total=None, connect=20, sock_connect=20, sock_read=None
        )
        auth = FoxAuth(self.settings)
        writer_task = asyncio.create_task(self.writer.run(), name="dynamodb-writer")
        attempt = 0
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                while not self.stop_event.is_set():
                    try:
                        await self.authenticate(session, auth)
                        useful = await self.consume_connection(session)
                        attempt = 0 if useful else attempt + 1
                        if not self.stop_event.is_set():
                            self.health.reconnect_count += 1
                    except aiohttp.WSServerHandshakeError as exc:
                        self.health.connected = False
                        code = f"WS_HANDSHAKE_{exc.status}"
                        self.health.last_error_code = code
                        self.health.last_error_message = "FoxESS WebSocket handshake failed"
                        if exc.status in (401, 403):
                            self.token = None
                        log_event("ws_connection_error", error_code=code)
                        attempt += 1
                    except AuthError as exc:
                        self.health.connected = False
                        self.health.last_error_code = "FOXESS_AUTH_FAILED"
                        self.health.last_error_message = safe_error(exc)
                        self.token = None
                        log_event("ws_auth_error", error_code="FOXESS_AUTH_FAILED",
                                  error_message=safe_error(exc))
                        attempt += 1
                    except ProtocolError as exc:
                        self.health.connected = False
                        self.health.last_error_code = "FOXESS_PROTOCOL_ERROR"
                        self.health.last_error_message = safe_error(exc)
                        self.token = None
                        log_event("ws_protocol_error",
                                  error_code="FOXESS_PROTOCOL_ERROR",
                                  error_message=safe_error(exc))
                        attempt += 1
                    except (aiohttp.ClientError, OSError, asyncio.TimeoutError) as exc:
                        self.health.connected = False
                        self.health.last_error_code = "FOXESS_NETWORK_ERROR"
                        self.health.last_error_message = safe_error(exc)
                        log_event("ws_connection_error", error_code="FOXESS_NETWORK_ERROR",
                                  exception_type=type(exc).__name__)
                        attempt += 1
                    except Exception as exc:
                        self.health.connected = False
                        self.health.last_error_code = "WS_COLLECTOR_UNEXPECTED"
                        self.health.last_error_message = safe_error(exc)
                        log_event("ws_connection_error", error_code="WS_COLLECTOR_UNEXPECTED",
                                  exception_type=type(exc).__name__,
                                  error_message=safe_error(exc))
                        attempt += 1
                    if self.stop_event.is_set():
                        break
                    delay = min(300.0, max(2.0, 2 ** min(attempt, 8)))
                    delay += random.random() * min(5.0, delay * 0.2)
                    self.health.transition("RECOVERING", "bounded_backoff")
                    log_event("ws_reconnect_backoff", delay_seconds=round(delay, 2),
                              attempt=attempt)
                    try:
                        await asyncio.wait_for(self.stop_event.wait(), timeout=delay)
                    except asyncio.TimeoutError:
                        pass
        finally:
            self.health.connected = False
            self.health.transition("STOPPING", "sigterm_or_shutdown")
            await self.writer.stop()
            await writer_task
            log_event("ws_collector_stopped", version=VERSION)


async def async_main() -> int:
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        log_event("ws_config_error", error_code="CONFIG_INVALID", error_message=str(exc))
        return 2
    service = Service(settings)
    loop = asyncio.get_running_loop()
    for name in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(name, service.request_stop)
        except NotImplementedError:
            pass
    log_event("ws_collector_start", version=VERSION, site_id=settings.site_id,
              table_name=settings.table_name, region=settings.aws_region)
    await service.run()
    return 0


def main() -> int:
    return asyncio.run(async_main())


if __name__ == "__main__":
    raise SystemExit(main())
