"""Unified read model for the legacy REST and fast WebSocket historians.

This module is deliberately read-only.  It never migrates, interpolates, or
writes historian data; source selection happens at query time using a
Melbourne-local calendar boundary.
"""

from __future__ import annotations

import math
import os
import time
from datetime import date, datetime

from common import AppError, METRICS, ZONE, iso
from telemetry_storage import gap_metadata, telemetry_history


DEFAULT_FAST_TELEMETRY_START_DATE = date(2026, 10, 1)


def fast_telemetry_start_date() -> date:
    value = os.environ.get(
        "FAST_TELEMETRY_START_DATE", DEFAULT_FAST_TELEMETRY_START_DATE.isoformat()
    ).strip()
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AppError(503, "FAST_TELEMETRY_START_DATE_INVALID",
                       "FAST_TELEMETRY_START_DATE must use YYYY-MM-DD.") from None
    if parsed.year < 2020:
        raise AppError(503, "FAST_TELEMETRY_START_DATE_INVALID",
                       "FAST_TELEMETRY_START_DATE cannot be earlier than 2020-01-01.")
    return parsed


def boundary_epoch_ms() -> int:
    boundary = fast_telemetry_start_date()
    return int(datetime.combine(boundary, datetime.min.time(), ZONE).timestamp() * 1000)


def segment_window(window, start_ms, end_ms):
    start = datetime.fromtimestamp(start_ms / 1000, ZONE)
    end = datetime.fromtimestamp(end_ms / 1000, ZONE)
    last = datetime.fromtimestamp((end_ms - 1) / 1000, ZONE)
    return {
        **window,
        "start_date": start.date().isoformat(),
        "end_date": last.date().isoformat(),
        "start_at": start.isoformat(timespec="seconds"),
        "end_at": end.isoformat(timespec="seconds"),
        "start_ms": start_ms,
        "end_ms": end_ms,
        "key": f"{start_ms}/{end_ms}",
    }


def resolution_policy(params, window):
    """Return the server-side resolution policy for the selected period."""
    requested = str(params.get("resolution", "auto")).strip().lower()
    explicit = {
        "5s": (5, "5s_raw", "5s"),
        "raw": (5, "5s_raw", "5s"),
        "1m": (60, "60s_server", "1m"),
        "60": (60, "60s_server", "1m"),
        "15m": (900, "900s_server", "15m"),
        "900": (900, "900s_server", "15m"),
    }
    if requested != "auto":
        if requested not in explicit:
            raise AppError(400, "INVALID_RESOLUTION", "Unsupported history resolution.")
        return explicit[requested]

    mode = str(params.get("range", window.get("preset", ""))).lower()
    duration = int(window["end_ms"]) - int(window["start_ms"])
    if mode in {"day", "today", "yesterday"} or duration <= 2 * 86400 * 1000:
        return 5, "5s_raw", "5s"
    if mode == "week" or duration <= 14 * 86400 * 1000:
        return 60, "60s_server", "1m"
    if mode == "month" or duration <= 62 * 86400 * 1000:
        return 900, "900s_server", "15m"
    # Quarter/year keep the same 15-minute server-side ceiling for now.  A
    # viewport-aware LOD endpoint can replace this policy without changing the
    # frontend's absolute-time contract.
    return 900, "900s_server", "15m"


def _series_map(series):
    output = {}
    for row in series or []:
        metric = row.get("metric")
        if metric:
            output[metric] = row
    return output


def merge_series(*groups):
    """Merge, de-duplicate and chronologically sort normalized point arrays."""
    metrics = [(metric, unit) for metric, unit in METRICS.values()]
    known = {metric for metric, _unit in metrics}
    for group in groups:
        for row in group or []:
            metric = row.get("metric")
            if metric and metric not in known:
                metrics.append((metric, row.get("unit", "")))
                known.add(metric)
    merged = []
    for metric, unit in metrics:
        values = {}
        for group in groups:
            row = _series_map(group).get(metric)
            if not row:
                continue
            for point in row.get("points") or []:
                if not isinstance(point, (list, tuple)) or len(point) < 2:
                    continue
                try:
                    stamp = int(point[0])
                except (TypeError, ValueError, OverflowError):
                    continue
                value = point[1]
                if value is not None:
                    try:
                        numeric = float(value)
                    except (TypeError, ValueError):
                        numeric = None
                    value = numeric if numeric is not None and math.isfinite(numeric) else None
                # A later source wins only at the exact same timestamp.  Source
                # ranges normally do not overlap because the boundary is strict.
                values[stamp] = value
        merged.append({"metric": metric, "unit": unit,
                       "points": [[stamp, values[stamp]] for stamp in sorted(values)]})
    return merged


def latest_from_series(series):
    latest = {}
    for row in series or []:
        metric = row.get("metric")
        for point in reversed(row.get("points") or []):
            if len(point) >= 2 and point[1] is not None:
                latest[metric] = {"t": int(point[0]), "value": point[1], "quality": "good"}
                break
    return latest


def newest_timestamp(series):
    stamps = [int(point[0]) for row in series or [] for point in row.get("points") or []
              if isinstance(point, (list, tuple)) and point]
    return max(stamps) if stamps else None


def quality_from_series(series, expected_seconds):
    """Summarise real timestamps without inserting or interpolating points."""
    stamps = {
        int(point[0])
        for row in series or []
        for point in row.get("points") or []
        if isinstance(point, (list, tuple)) and point
    }
    return {
        "observed_timestamps": len(stamps),
        "expected_cadence_seconds": expected_seconds,
        **gap_metadata(stamps, expected_seconds),
    }


def unified_history(params, now, window, legacy_reader, telemetry_store):
    """Build one logical response while keeping datasource routing server-side."""
    boundary_ms = boundary_epoch_ms()
    resolution_seconds, resolution_label, fast_resolution = resolution_policy(params, window)
    start_ms, end_ms = int(window["start_ms"]), int(window["end_ms"])
    legacy = None
    fast = None
    fast_error = None
    fast_start = max(start_ms, boundary_ms)
    fast_supported = end_ms > fast_start and (end_ms - start_ms) <= 367 * 86400 * 1000
    legacy_end = min(end_ms, boundary_ms)

    if start_ms < legacy_end:
        legacy_window = segment_window(window, start_ms, legacy_end)
        legacy = legacy_reader(legacy_window)

    if fast_supported:
        fast_window = segment_window(window, fast_start, end_ms)
        fast_params = {**params, "source": "foxess_ws", "resolution": fast_resolution}
        try:
            fast = telemetry_history(fast_params, now, fast_window, telemetry_store)
        except AppError as exc:
            fast_error = {"code": exc.code, "message": exc.message}

    legacy_series = legacy.get("series", []) if legacy else []
    fast_series = fast.get("series", []) if fast else []
    series = merge_series(legacy_series, fast_series)
    fast_cursor = newest_timestamp(fast_series)
    latest = dict((legacy or {}).get("latest") or {})
    latest.update(latest_from_series(fast_series))
    collector = (legacy or {}).get("collector") or {}
    health = (fast or {}).get("collector") or {}
    valid_latest = [int(item["t"]) for item in latest.values()
                    if isinstance(item, dict) and item.get("value") is not None and item.get("t")]
    legacy_quality = quality_from_series(legacy_series, 300) if legacy else None
    fast_quality = (fast or {}).get("coverage")
    quality_parts = [item for item in (legacy_quality, fast_quality) if item]
    largest_gaps = [item.get("largest_gap_seconds") for item in quality_parts
                    if item.get("largest_gap_seconds") is not None]
    missing_durations = [item.get("missing_duration_seconds") for item in quality_parts
                         if item.get("missing_duration_seconds") is not None]
    data_quality = {
        "legacy": legacy_quality,
        "fast": fast_quality,
        "largest_gap_seconds": max(largest_gaps) if largest_gaps else None,
        "missing_duration_seconds": round(sum(missing_durations), 1),
        "last_fresh_sample_age_seconds": health.get("last_fresh_age_seconds"),
    }

    source_segments = []
    if legacy:
        source_segments.append({
            "source": "rest_5m",
            "start_ms": int(legacy["range"]["start_ms"]),
            "end_ms": int(legacy["range"]["end_ms"]),
            "available": any(row.get("points") for row in legacy_series),
            "resolution_seconds": 300,
        })
    if fast_supported:
        source_segments.append({
            "source": "ws_fast",
            "start_ms": fast_start,
            "end_ms": end_ms,
            "available": bool(fast and fast.get("available")),
            "resolution_seconds": fast.get("resolution_seconds") if fast else resolution_seconds,
            "error": fast_error,
        })

    warnings = list((legacy or {}).get("warnings") or [])
    if fast_error:
        warnings.append(f"Fast telemetry unavailable: {fast_error['code']}")
    return {
        "source": "hybrid_historian",
        "timezone": "Australia/Melbourne",
        "range": window,
        "resolution": resolution_label,
        "resolution_seconds": resolution_seconds,
        "resolution_authority": "server",
        "series": series,
        "latest": latest,
        "latest_observed_at": iso(max(valid_latest) / 1000) if valid_latest else None,
        "last_source_timestamp": fast_cursor,
        "max_gap_seconds": data_quality["largest_gap_seconds"],
        "data_quality": data_quality,
        "warnings": warnings,
        "collector": collector,
        "telemetry_health": health,
        "source_boundary": {
            "timezone": "Australia/Melbourne",
            "fast_telemetry_start_date": fast_telemetry_start_date().isoformat(),
            "epoch_ms": boundary_ms,
            "before": "rest_5m",
            "from_boundary": "ws_fast",
        },
        "source_segments": source_segments,
        "gap_semantics": {
            "storage": "missing_samples_remain_absent",
            "presentation": "connect_real_samples_only",
            "synthetic_points": False,
        },
        "checked_at": iso(time.time()),
    }
