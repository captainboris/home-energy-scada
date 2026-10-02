"""Asynchronous queue consumer for raw telemetry, rollups, and health state."""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable
from zoneinfo import ZoneInfo

from .health import Health, log_event
from .model import POWER_METRICS, TelemetrySample


def decimalise(value):
    if isinstance(value, float):
        return Decimal(str(round(value, 9)))
    if isinstance(value, dict):
        return {key: decimalise(item) for key, item in value.items()}
    if isinstance(value, list):
        return [decimalise(item) for item in value]
    return value


def condition_failed(exc: Exception) -> bool:
    response = getattr(exc, "response", None) or {}
    return (response.get("Error") or {}).get("Code") == "ConditionalCheckFailedException"


@dataclass
class MetricStats:
    count: int = 0
    total: float = 0.0
    minimum: float | None = None
    maximum: float | None = None
    last: float | None = None
    min_ts: int | None = None
    max_ts: int | None = None
    last_ts: int | None = None

    def add(self, stamp: int, value: float | None) -> None:
        if value is None:
            return
        self.count += 1
        self.total += value
        self.last, self.last_ts = value, stamp
        if self.minimum is None or value < self.minimum:
            self.minimum, self.min_ts = value, stamp
        if self.maximum is None or value > self.maximum:
            self.maximum, self.max_ts = value, stamp

    def item(self) -> dict:
        return {
            "count": self.count,
            "min": self.minimum,
            "max": self.maximum,
            "avg": round(self.total / self.count, 6) if self.count else None,
            "last": self.last,
            "min_ts": self.min_ts,
            "max_ts": self.max_ts,
            "last_ts": self.last_ts,
        }


@dataclass
class MinuteRollup:
    bucket_start_ms: int
    seen: set[int] = field(default_factory=set)
    metrics: dict[str, MetricStats] = field(
        default_factory=lambda: {metric: MetricStats() for metric in POWER_METRICS}
    )

    def add(self, sample: TelemetrySample) -> bool:
        if sample.source_epoch_ms in self.seen:
            return False
        self.seen.add(sample.source_epoch_ms)
        for metric in POWER_METRICS:
            self.metrics[metric].add(sample.source_epoch_ms, getattr(sample, metric))
        return True

    def item(self, site_id: str, timezone_name: str) -> dict:
        local = datetime.fromtimestamp(self.bucket_start_ms / 1000, ZoneInfo(timezone_name))
        return {
            "pk": f"SITE#{site_id}#DAY#{local.date().isoformat()}",
            "sk": f"ROLLUP#60#{self.bucket_start_ms:013d}",
            "bucket_start_ms": self.bucket_start_ms,
            "bucket_seconds": 60,
            "sample_count": len(self.seen),
            "expected_samples": 12,
            "source_first_ms": min(self.seen) if self.seen else None,
            "source_last_ms": max(self.seen) if self.seen else None,
            "metrics": {key: value.item() for key, value in self.metrics.items()},
            "source": "foxess_ws",
        }


class DynamoWriter:
    def __init__(self, settings, health: Health, table=None,
                 sleep: Callable[[float], object] = asyncio.sleep):
        self.settings = settings
        self.health = health
        self.sleep = sleep
        if table is None:
            import boto3
            from botocore.config import Config
            table = boto3.resource(
                "dynamodb",
                region_name=settings.aws_region,
                config=Config(connect_timeout=3, read_timeout=5,
                              retries={"mode": "standard", "total_max_attempts": 5}),
            ).Table(settings.table_name)
        self.table = table
        self.queue: asyncio.Queue[TelemetrySample | None] = asyncio.Queue(
            maxsize=settings.queue_size
        )
        self.rollups: dict[int, MinuteRollup] = {}
        self._last_health_write = 0.0
        self._stopping = False

    def enqueue(self, sample: TelemetrySample) -> bool:
        try:
            self.queue.put_nowait(sample)
            return True
        except asyncio.QueueFull:
            self.health.queue_overflow()
            log_event("ws_queue_overflow", queue_depth=self.queue.qsize(),
                      queue_capacity=self.settings.queue_size)
            return False

    async def _call(self, function, *args, **kwargs):
        return await asyncio.to_thread(function, *args, **kwargs)

    async def _put_raw(self, sample: TelemetrySample) -> bool:
        try:
            await self._call(
                self.table.put_item,
                Item=decimalise(sample.item(self.settings.site_id, self.settings.timezone)),
                ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
            )
            return True
        except Exception as exc:
            if condition_failed(exc):
                return False
            raise

    def _rollup_for(self, stamp_ms: int) -> MinuteRollup:
        bucket = stamp_ms - stamp_ms % 60_000
        if bucket not in self.rollups:
            self.rollups[bucket] = MinuteRollup(bucket)
        # Keep a short reconciliation window without unbounded memory growth.
        for old in sorted(self.rollups)[:-6]:
            self.rollups.pop(old, None)
        return self.rollups[bucket]

    async def _put_rollup(self, rollup: MinuteRollup) -> None:
        await self._call(
            self.table.put_item,
            Item=decimalise(rollup.item(self.settings.site_id, self.settings.timezone)),
        )

    async def write_sample(self, sample: TelemetrySample) -> None:
        last_exc = None
        for attempt in range(1, 5):
            try:
                await self._put_raw(sample)
                rollup = self._rollup_for(sample.source_epoch_ms)
                rollup.add(sample)
                await self._put_rollup(rollup)
                self.health.wrote(sample.source_epoch_ms)
                return
            except Exception as exc:
                last_exc = exc
                if attempt == 4:
                    break
                delay = min(4.0, 0.25 * (2 ** (attempt - 1))) + random.random() * 0.1
                await self.sleep(delay)
        code = type(last_exc).__name__ if last_exc else "DYNAMODB_WRITE_FAILED"
        self.health.write_failed(code, str(last_exc or "unknown write failure"))
        log_event("ws_write_error", error_code=code,
                  error_message=str(last_exc or "unknown")[:300],
                  source_epoch_ms=sample.source_epoch_ms)
        raise last_exc or RuntimeError("DynamoDB write failed")

    async def write_health(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_health_write < self.settings.health_write_seconds:
            return
        snapshot = self.health.snapshot(
            self.settings.site_id, self.queue.qsize()
        )
        try:
            await self._call(self.table.put_item, Item=decimalise(snapshot))
            self._last_health_write = now
            log_event(
                "ws_health",
                healthy=snapshot["healthy"], state=snapshot["state"],
                connected=snapshot["connected"],
                last_source_epoch_ms=snapshot["last_source_epoch_ms"],
                fresh_frames=snapshot["fresh_frames"],
                stale_frames=snapshot["stale_frames"],
                cached_frames=snapshot["cached_frames"],
                duplicate_frames=snapshot["duplicate_frames"],
                writes=snapshot["writes"], write_errors=snapshot["write_errors"],
                queue_depth=snapshot["queue_depth"],
                reconnect_count=snapshot["reconnect_count"],
            )
        except Exception as exc:
            self.health.write_failed(type(exc).__name__, str(exc))
            log_event("ws_health_write_error", error_code=type(exc).__name__,
                      error_message=str(exc)[:300])

    def _sample_from_item(self, item: dict) -> TelemetrySample:
        def value(name):
            raw = item.get(name)
            return float(raw) if raw is not None else None
        return TelemetrySample(
            source_epoch_ms=int(item["source_epoch_ms"]),
            received_at_ms=int(item.get("received_at_ms", item["source_epoch_ms"])),
            time_diff_seconds=value("time_diff_seconds") or 0.0,
            pv_power_kw=value("pv_power_kw"), load_power_kw=value("load_power_kw"),
            grid_power_kw=value("grid_power_kw"),
            grid_import_power_kw=value("grid_import_power_kw"),
            grid_export_power_kw=value("grid_export_power_kw"),
            battery_power_kw=value("battery_power_kw"),
            battery_charge_power_kw=value("battery_charge_power_kw"),
            battery_discharge_power_kw=value("battery_discharge_power_kw"),
            battery_soc_pct=value("battery_soc_pct"),
            grid_direction_code=int(item["grid_direction_code"]) if item.get("grid_direction_code") is not None else None,
            battery_direction_code=int(item["battery_direction_code"]) if item.get("battery_direction_code") is not None else None,
            work_mode=item.get("work_mode"),
        )

    async def rebuild_recent_rollups(self, now_ms: int | None = None) -> int:
        """Rebuild the last ten minutes after restart from durable raw items."""
        now_ms = now_ms or int(time.time() * 1000)
        existing_health = await self._call(
            self.table.get_item,
            Key={"pk": f"SITE#{self.settings.site_id}", "sk": "STATE#ws_collector"},
            ConsistentRead=True,
        )
        previous_first = (existing_health.get("Item") or {}).get("first_source_epoch_ms")
        if previous_first:
            self.health.first_source_timestamp_ms = int(previous_first)
        start_ms = now_ms - 10 * 60_000
        zone = ZoneInfo(self.settings.timezone)
        first = datetime.fromtimestamp(start_ms / 1000, zone).date()
        last = datetime.fromtimestamp(now_ms / 1000, zone).date()
        cursor = first
        rows = []
        while cursor <= last:
            pk = f"SITE#{self.settings.site_id}#DAY#{cursor.isoformat()}"
            request = {
                "KeyConditionExpression": "#pk = :pk AND #sk BETWEEN :lo AND :hi",
                "ExpressionAttributeNames": {"#pk": "pk", "#sk": "sk"},
                "ExpressionAttributeValues": {
                    ":pk": pk,
                    ":lo": f"TS#{start_ms:013d}",
                    ":hi": f"TS#{now_ms:013d}",
                },
            }
            while True:
                result = await self._call(self.table.query, **request)
                rows.extend(result.get("Items", []))
                if not result.get("LastEvaluatedKey"):
                    break
                request["ExclusiveStartKey"] = result["LastEvaluatedKey"]
            cursor += timedelta(days=1)
        for item in rows:
            sample = self._sample_from_item(item)
            self._rollup_for(sample.source_epoch_ms).add(sample)
        for rollup in self.rollups.values():
            await self._put_rollup(rollup)
        if rows:
            log_event("ws_rollup_rebuilt", raw_samples=len(rows),
                      rollup_buckets=len(self.rollups))
        return len(rows)

    async def run(self) -> None:
        try:
            await self.rebuild_recent_rollups()
        except Exception as exc:
            self.health.write_failed("ROLLUP_REBUILD_FAILED", str(exc))
            log_event("ws_rollup_rebuild_error", error_code=type(exc).__name__,
                      error_message=str(exc)[:300])
        while True:
            try:
                sample = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                await self.write_health()
                if self._stopping and self.queue.empty():
                    break
                continue
            try:
                if sample is None:
                    break
                await self.write_sample(sample)
            except Exception:
                # The error is already represented in health and structured logs.
                pass
            finally:
                self.queue.task_done()
            await self.write_health()
        await self.write_health(force=True)

    async def stop(self) -> None:
        self._stopping = True
        await self.queue.join()
        await self.queue.put(None)
