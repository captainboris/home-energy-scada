"""Read-only Web/API adapter for the independent fast-telemetry table."""

from __future__ import annotations

import math
import os
import time
from datetime import datetime, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError

from common import AppError, ZONE, iso


TELEMETRY_METRICS = (
    ("pv_power_kw", "kW"),
    ("load_power_kw", "kW"),
    ("grid_import_power_kw", "kW"),
    ("grid_export_power_kw", "kW"),
    ("battery_charge_power_kw", "kW"),
    ("battery_discharge_power_kw", "kW"),
    ("battery_soc_pct", "%"),
)
MAX_RAW_MS = 2 * 86400 * 1000
MAX_TELEMETRY_MS = 367 * 86400 * 1000
MAX_LIVE_CATCHUP_MS = 2 * 86400 * 1000


def table_name() -> str:
    configured = os.environ.get("TELEMETRY_TABLE_NAME", "").strip()
    if configured:
        return configured
    history = os.environ.get("TABLE_NAME", "").strip()
    if history.endswith("-history"):
        return history[:-8] + "-telemetry"
    return ""


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


class TelemetryStore:
    def __init__(self, table=None, site=None):
        self.site = site or os.environ.get("SITE_ID", "home")
        name = table_name()
        if table is None and not name:
            raise AppError(503, "TELEMETRY_NOT_CONFIGURED",
                           "Fast telemetry table is not configured.")
        self.table = table or boto3.resource(
            "dynamodb",
            config=Config(connect_timeout=3, read_timeout=8,
                          retries={"mode": "standard", "total_max_attempts": 4}),
        ).Table(name)

    def site_key(self):
        return "SITE#" + self.site

    def day_key(self, day):
        return f"{self.site_key()}#DAY#{day.isoformat()}"

    def health(self):
        try:
            return self.table.get_item(
                Key={"pk": self.site_key(), "sk": "STATE#ws_collector"},
                ConsistentRead=True,
            ).get("Item")
        except ClientError as exc:
            self._raise_client_error(exc)

    def _raise_client_error(self, exc):
        code = (exc.response.get("Error") or {}).get("Code", "")
        if code == "ResourceNotFoundException":
            raise AppError(503, "TELEMETRY_TABLE_NOT_FOUND",
                           "Fast telemetry table does not exist.") from None
        if code in {"AccessDeniedException", "UnauthorizedOperation"}:
            raise AppError(503, "TELEMETRY_ACCESS_DENIED",
                           "Web API cannot read the fast telemetry table.") from None
        raise

    def _query_day(self, day, prefix, lower, upper):
        request = {
            "KeyConditionExpression": (
                Key("pk").eq(self.day_key(day))
                & Key("sk").between(prefix + f"{lower:013d}",
                                     prefix + f"{upper:013d}")
            ),
            "ConsistentRead": False,
        }
        rows = []
        while True:
            try:
                result = self.table.query(**request)
            except ClientError as exc:
                self._raise_client_error(exc)
            rows.extend(result.get("Items", []))
            if not result.get("LastEvaluatedKey"):
                return rows
            request["ExclusiveStartKey"] = result["LastEvaluatedKey"]

    def query(self, start_ms, end_ms, raw):
        if end_ms <= start_ms:
            return []
        first = datetime.fromtimestamp(start_ms / 1000, ZONE).date()
        last = datetime.fromtimestamp((end_ms - 1) / 1000, ZONE).date()
        prefix = "TS#" if raw else "ROLLUP#60#"
        rows = []
        day = first
        while day <= last:
            rows.extend(self._query_day(day, prefix, start_ms, end_ms - 1))
            day += timedelta(days=1)
        stamp = "source_epoch_ms" if raw else "bucket_start_ms"
        return sorted(
            (row for row in rows if start_ms <= int(row.get(stamp, 0)) < end_ms),
            key=lambda row: int(row[stamp]),
        )


def choose_resolution(params, duration_ms):
    requested = str(params.get("resolution", "auto")).strip().lower()
    if requested == "auto":
        if duration_ms <= MAX_RAW_MS:
            return "raw", 5
        if duration_ms <= 14 * 86400 * 1000:
            return "rollup", 60
        return "rollup", 900
    aliases = {"raw": ("raw", 5), "5s": ("raw", 5),
               "60": ("rollup", 60), "1m": ("rollup", 60),
               "300": ("rollup", 300), "5m": ("rollup", 300),
               "900": ("rollup", 900), "15m": ("rollup", 900)}
    if requested not in aliases:
        raise AppError(400, "INVALID_RESOLUTION", "Unsupported telemetry resolution.")
    mode, seconds = aliases[requested]
    if mode == "raw" and duration_ms > MAX_RAW_MS:
        raise AppError(400, "RAW_RANGE_TOO_LONG", "Raw 5-second telemetry is limited to two days.")
    return mode, seconds


def _empty_stats():
    return {"count": 0, "sum": 0.0, "min": None, "max": None,
            "last": None, "min_ts": None, "max_ts": None, "last_ts": None}


def _merge_stat(target, source):
    count = int(source.get("count", 0) or 0)
    average = number(source.get("avg"))
    if count and average is not None:
        target["count"] += count
        target["sum"] += average * count
    minimum, maximum = number(source.get("min")), number(source.get("max"))
    if minimum is not None and (target["min"] is None or minimum < target["min"]):
        target["min"], target["min_ts"] = minimum, int(source.get("min_ts") or 0)
    if maximum is not None and (target["max"] is None or maximum > target["max"]):
        target["max"], target["max_ts"] = maximum, int(source.get("max_ts") or 0)
    last = number(source.get("last"))
    last_ts = int(source.get("last_ts") or 0)
    if last is not None and last_ts >= (target["last_ts"] or 0):
        target["last"], target["last_ts"] = last, last_ts


def aggregate_rollups(rows, resolution_seconds):
    buckets = {}
    width = resolution_seconds * 1000
    for row in rows:
        source_bucket = int(row["bucket_start_ms"])
        bucket = source_bucket - source_bucket % width
        target = buckets.setdefault(bucket, {
            "bucket_start_ms": bucket,
            "sample_count": 0,
            "source_first_ms": None,
            "source_last_ms": None,
            "metrics": {metric: _empty_stats() for metric, _unit in TELEMETRY_METRICS},
        })
        target["sample_count"] += int(row.get("sample_count", 0) or 0)
        first = int(row.get("source_first_ms") or 0)
        last = int(row.get("source_last_ms") or 0)
        if first and (target["source_first_ms"] is None or first < target["source_first_ms"]):
            target["source_first_ms"] = first
        if last and (target["source_last_ms"] is None or last > target["source_last_ms"]):
            target["source_last_ms"] = last
        metrics = row.get("metrics") or {}
        for metric, _unit in TELEMETRY_METRICS:
            if isinstance(metrics.get(metric), dict):
                _merge_stat(target["metrics"][metric], metrics[metric])
    return [buckets[key] for key in sorted(buckets)]


def raw_series(rows):
    output = []
    for metric, unit in TELEMETRY_METRICS:
        points = []
        for row in rows:
            value = number(row.get(metric))
            points.append([int(row["source_epoch_ms"]), value])
        output.append({"metric": metric, "unit": unit, "points": points})
    return output


def rollup_series(buckets):
    output = []
    for metric, unit in TELEMETRY_METRICS:
        points, envelope = [], []
        for bucket in buckets:
            stat = bucket["metrics"][metric]
            count = stat["count"]
            if not count:
                continue
            average = stat["sum"] / count
            candidates = {
                (stat["min_ts"], stat["min"]),
                (stat["max_ts"], stat["max"]),
                (stat["last_ts"], stat["last"]),
            }
            valid_candidates = [
                (stamp, value) for stamp, value in candidates
                if stamp and value is not None
            ]
            points.extend([[int(stamp), value]
                           for stamp, value in sorted(valid_candidates)])
            envelope.append([
                bucket["bucket_start_ms"], stat["min"], stat["max"],
                round(average, 6), stat["last"], stat["min_ts"],
                stat["max_ts"], stat["last_ts"], count,
            ])
        output.append({"metric": metric, "unit": unit, "points": points,
                       "envelope": envelope,
                       "plot_strategy": "min_max_last"})
    return output


def telemetry_peaks(start_ms, end_ms, metrics, store=None):
    """Return exact observed maxima without using averaged display points.

    Short ranges read genuine 5-second rows. Longer ranges read the persisted
    one-minute ``max`` and ``max_ts`` metadata, so a Week/Month request does not
    download the complete 5-second dataset and still retains the winning raw
    sample timestamp.
    """
    store = store or TelemetryStore()
    start_ms, end_ms = int(start_ms), int(end_ms)
    metrics = tuple(metrics)
    winners = {metric: None for metric in metrics}
    raw = end_ms - start_ms <= MAX_RAW_MS
    if raw:
        rows = store.query(start_ms, end_ms, True)
        for row in rows:
            stamp = int(row.get("source_epoch_ms") or 0)
            for metric in metrics:
                value = number(row.get(metric))
                if value is not None and (winners[metric] is None or value > winners[metric][0]):
                    winners[metric] = (value, stamp)
        source = "fast_telemetry_raw"
        resolution_seconds = 5
    else:
        query_start = start_ms - start_ms % 60_000
        rows = store.query(query_start, end_ms, False)
        for row in rows:
            stats = row.get("metrics") or {}
            for metric in metrics:
                stat = stats.get(metric) if isinstance(stats, dict) else None
                if not isinstance(stat, dict):
                    continue
                value = number(stat.get("max"))
                stamp = int(stat.get("max_ts") or 0)
                if (value is not None and start_ms <= stamp < end_ms
                        and (winners[metric] is None or value > winners[metric][0])):
                    winners[metric] = (value, stamp)
        source = "fast_telemetry_rollup_max"
        resolution_seconds = 60

    output = {}
    for metric, winner in winners.items():
        output[metric] = ({
            "kw": round(winner[0], 3),
            "time": iso(winner[1] / 1000),
            "source": source,
            "sample_resolution_seconds": resolution_seconds,
        } if winner else {
            "kw": None,
            "time": None,
            "source": source,
            "sample_resolution_seconds": resolution_seconds,
        })
    return output


def gap_metadata(stamps, expected_seconds):
    stamps = sorted(set(int(value) for value in stamps if value))
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]
    expected_ms = expected_seconds * 1000
    return {
        "largest_gap_seconds": round(max(gaps) / 1000, 1) if gaps else None,
        "gap_count": sum(gap > expected_ms * 1.5 for gap in gaps),
        "missing_duration_seconds": round(
            sum(max(0, gap - expected_ms) for gap in gaps) / 1000, 1
        ),
    }


def telemetry_history(params, now, window, store=None):
    if params.get("source") not in (None, "", "foxess_ws"):
        raise AppError(400, "INVALID_SOURCE", "Only source=foxess_ws is supported.")
    duration = window["end_ms"] - window["start_ms"]
    if duration > MAX_TELEMETRY_MS:
        raise AppError(400, "TELEMETRY_RANGE_TOO_LONG",
                       "Fast telemetry queries are limited to 367 days.")
    mode, resolution_seconds = choose_resolution(params, duration)
    store = store or TelemetryStore()
    effective_end = min(window["end_ms"], int(now * 1000) + 1)
    rows = store.query(window["start_ms"], effective_end, mode == "raw")
    health = store.health() or {}
    if mode == "raw":
        series = raw_series(rows)
        sample_count = len(rows)
        stamps = [int(row["source_epoch_ms"]) for row in rows]
        resolution_label = "5s_raw"
    else:
        buckets = aggregate_rollups(rows, resolution_seconds)
        series = rollup_series(buckets)
        sample_count = sum(int(row.get("sample_count", 0) or 0) for row in rows)
        stamps = [int(row.get("source_first_ms") or 0) for row in rows]
        resolution_label = f"{resolution_seconds}s_rollup"

    first_available = int(health.get("first_source_epoch_ms") or 0) or (
        min(stamps) if stamps else None
    )
    denominator_start = max(window["start_ms"], first_available or window["start_ms"])
    expected = max(0, math.floor((effective_end - denominator_start) / 5000))
    coverage = round(min(100.0, sample_count / expected * 100), 1) if expected else None
    gaps = gap_metadata(stamps, 5 if mode == "raw" else 60)
    last_source_ms = int(health.get("last_source_epoch_ms") or 0) or None
    return {
        "available": bool(rows),
        "reason": None if rows else "no_fast_telemetry_for_range",
        "source": "foxess_ws",
        "timezone": "Australia/Melbourne",
        "range": window,
        "resolution": resolution_label,
        "resolution_seconds": resolution_seconds,
        "max_gap_seconds": 15 if mode == "raw" else resolution_seconds * 2,
        "series": series,
        "coverage": {
            "theoretical_samples": expected,
            "fresh_samples": sample_count,
            "coverage_pct": coverage,
            **gaps,
        },
        "collector": {
            "healthy": bool(health.get("healthy")),
            "state": health.get("state"),
            "connected": bool(health.get("connected")),
            "last_source_epoch_ms": last_source_ms,
            "last_fresh_age_seconds": (
                round(max(0.0, now - last_source_ms / 1000), 1)
                if last_source_ms else None
            ),
            "last_fresh_sample_at": health.get("last_fresh_sample_at"),
            "last_write_at": health.get("last_write_at"),
            "reconnect_count": int(health.get("reconnect_count", 0) or 0),
            "write_errors": int(health.get("write_errors", 0) or 0),
            "collector_version": health.get("collector_version"),
        },
        "first_available_at": iso(first_available / 1000) if first_available else None,
        "checked_at": iso(time.time()),
    }


def telemetry_health(store=None):
    store = store or TelemetryStore()
    item = store.health()
    return {
        "available": bool(item),
        "source": "foxess_ws",
        "health": item or {},
        "checked_at": iso(time.time()),
    }


def telemetry_incremental(params, now, store=None, minimum_ms=0):
    """Return genuine raw samples newer than the caller's source timestamp.

    ``since_ms`` is the historian source timestamp, not a browser receive time.
    The query remains a DynamoDB Query over one or more Melbourne day
    partitions, so a poll spanning local midnight cannot silently lose points.
    """
    try:
        since_ms = int(params.get("since_ms", params.get("since", minimum_ms - 1)))
    except (TypeError, ValueError, OverflowError):
        raise AppError(400, "INVALID_LIVE_CURSOR",
                       "since_ms must be a valid source timestamp.") from None
    now_ms = int(now * 1000)
    lower = max(int(minimum_ms), since_ms + 1)
    if lower > now_ms + 1000:
        raise AppError(400, "INVALID_LIVE_CURSOR",
                       "since_ms cannot be in the future.")
    if now_ms - lower > MAX_LIVE_CATCHUP_MS:
        raise AppError(400, "LIVE_CATCHUP_TOO_LONG",
                       "Incremental catch-up is limited to two days; reload the selected period.")

    store = store or TelemetryStore()
    rows = store.query(lower, now_ms + 1, True) if lower <= now_ms else []
    health = store.health() or {}
    health_last_source_ms = int(health.get("last_source_epoch_ms") or 0) or None
    series = raw_series(rows)
    stamps = [int(row["source_epoch_ms"]) for row in rows]
    latest_rows = rows
    newest_incremental_ms = max(
        (int(row.get("source_epoch_ms") or 0) for row in rows),
        default=0)
    if health_last_source_ms and health_last_source_ms > newest_incremental_ms:
        # Current Readings represent NOW independently of the selected
        # Historian period and live cursor. Fetch the one persisted row named
        # by collector health even when there are no newer incremental points.
        latest_rows = store.query(health_last_source_ms,
                                  health_last_source_ms + 1, True) or rows
    latest = {}
    for metric, _unit in TELEMETRY_METRICS:
        for row in reversed(latest_rows):
            value = number(row.get(metric))
            if value is not None:
                latest[metric] = {
                    "t": int(row["source_epoch_ms"]),
                    "value": value,
                    "quality": "good",
                }
                break
    last_source_ms = max(stamps) if stamps else since_ms
    return {
        "source": "foxess_ws",
        "timezone": "Australia/Melbourne",
        "resolution": "5s_raw",
        "resolution_seconds": 5,
        "since_ms": since_ms,
        "through_ms": last_source_ms,
        "points": series,
        "sample_count": len(rows),
        "latest": latest,
        "health": {
            "healthy": bool(health.get("healthy")),
            "state": health.get("state"),
            "connected": bool(health.get("connected")),
            "last_source_epoch_ms": health_last_source_ms,
            "last_fresh_age_seconds": (
                round(max(0.0, now - health_last_source_ms / 1000), 1)
                if health_last_source_ms else None
            ),
            "last_fresh_sample_at": health.get("last_fresh_sample_at"),
            "last_write_at": health.get("last_write_at"),
            "reconnect_count": int(health.get("reconnect_count", 0) or 0),
            "write_errors": int(health.get("write_errors", 0) or 0),
            "collector_version": health.get("collector_version"),
        },
        "checked_at": iso(time.time()),
    }
