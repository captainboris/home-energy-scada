"""Collector health counters and structured logging."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import VERSION


def iso_ms(epoch_ms: int | None) -> str | None:
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def log_event(event: str, **fields) -> None:
    safe = {"event": event, "at": iso_ms(int(time.time() * 1000)), **fields}
    print(json.dumps(safe, ensure_ascii=False, separators=(",", ":")), flush=True)


@dataclass
class Health:
    started_at_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    connected: bool = False
    state: str = "CONNECTING"
    last_frame_at_ms: int | None = None
    last_fresh_sample_at_ms: int | None = None
    last_write_at_ms: int | None = None
    last_source_timestamp_ms: int | None = None
    first_source_timestamp_ms: int | None = None
    current_time_diff: float | None = None
    total_frames: int = 0
    fresh_frames: int = 0
    stale_frames: int = 0
    cached_frames: int = 0
    duplicate_frames: int = 0
    invalid_frames: int = 0
    writes: int = 0
    write_errors: int = 0
    queue_overflows: int = 0
    reconnect_count: int = 0
    auth_refresh_count: int = 0
    last_error_code: str | None = None
    last_error_message: str | None = None

    def transition(self, state: str, reason: str | None = None) -> None:
        previous = self.state
        self.state = state
        if state != previous:
            log_event("ws_state_transition", previous=previous, state=state, reason=reason)

    def frame(self, received_at_ms: int) -> None:
        self.total_frames += 1
        self.last_frame_at_ms = received_at_ms

    def rejected(self, reason: str, time_diff: float | None = None) -> None:
        self.current_time_diff = time_diff
        if reason == "stale":
            self.stale_frames += 1
        elif reason == "cached":
            self.cached_frames += 1
        else:
            self.invalid_frames += 1

    def fresh(self, source_ms: int, received_ms: int, time_diff: float) -> None:
        self.fresh_frames += 1
        self.last_fresh_sample_at_ms = received_ms
        self.last_source_timestamp_ms = source_ms
        if self.first_source_timestamp_ms is None:
            self.first_source_timestamp_ms = source_ms
        self.current_time_diff = time_diff
        self.last_error_code = self.last_error_message = None

    def duplicate(self) -> None:
        self.duplicate_frames += 1

    def queue_overflow(self) -> None:
        self.queue_overflows += 1
        self.last_error_code = "WRITE_QUEUE_OVERFLOW"
        self.last_error_message = "bounded telemetry write queue is full"

    def wrote(self, source_ms: int) -> None:
        self.writes += 1
        self.last_write_at_ms = int(time.time() * 1000)
        self.last_source_timestamp_ms = max(self.last_source_timestamp_ms or 0, source_ms)
        # Error counters remain cumulative for observability, while current
        # health recovers after a later successful write.
        self.last_error_code = self.last_error_message = None

    def write_failed(self, code: str, message: str) -> None:
        self.write_errors += 1
        self.last_error_code = code
        self.last_error_message = str(message)[:300]

    def snapshot(self, site_id: str, queue_depth: int, now_ms: int | None = None) -> dict:
        now_ms = now_ms or int(time.time() * 1000)
        fresh_age = ((now_ms - self.last_fresh_sample_at_ms) / 1000
                     if self.last_fresh_sample_at_ms else None)
        write_age = ((now_ms - self.last_write_at_ms) / 1000
                     if self.last_write_at_ms else None)
        healthy = bool(
            self.connected
            and self.state == "LIVE"
            and fresh_age is not None and fresh_age <= 45
            and write_age is not None and write_age <= 60
            and self.last_error_code is None
        )
        return {
            "pk": f"SITE#{site_id}",
            "sk": "STATE#ws_collector",
            "connected": self.connected,
            "state": self.state,
            "healthy": healthy,
            "last_frame_at": iso_ms(self.last_frame_at_ms),
            "last_fresh_sample_at": iso_ms(self.last_fresh_sample_at_ms),
            "last_write_at": iso_ms(self.last_write_at_ms),
            "last_source_timestamp": iso_ms(self.last_source_timestamp_ms),
            "last_source_epoch_ms": self.last_source_timestamp_ms,
            "first_source_epoch_ms": self.first_source_timestamp_ms,
            "first_source_timestamp": iso_ms(self.first_source_timestamp_ms),
            "current_time_diff": self.current_time_diff,
            "fresh_frames": self.fresh_frames,
            "stale_frames": self.stale_frames,
            "cached_frames": self.cached_frames,
            "duplicate_frames": self.duplicate_frames,
            "invalid_frames": self.invalid_frames,
            "writes": self.writes,
            "write_errors": self.write_errors,
            "queue_depth": queue_depth,
            "queue_overflows": self.queue_overflows,
            "reconnect_count": self.reconnect_count,
            "auth_refresh_count": self.auth_refresh_count,
            "uptime_seconds": round((now_ms - self.started_at_ms) / 1000, 1),
            "collector_version": VERSION,
            "last_error_code": self.last_error_code,
            "last_error_message": self.last_error_message,
            "updated_at": iso_ms(now_ms),
        }
