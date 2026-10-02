"""Fail-closed FoxESS WebSocket frame parser.

The real KH capture established that server-pushed samples carry a non-zero
``result.consumeTs``. Quick responses to ``getdata`` use ``consumeTs=0`` even
when ``timeDiff`` is low. ``lastUpdateDate`` is only display text and is never
used as a historian timestamp.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .config import Settings
from .model import TelemetrySample


@dataclass(frozen=True)
class ParseResult:
    sample: TelemetrySample | None
    reason: str
    time_diff: float | None = None


def _number(value) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _code(value) -> int | None:
    number = _number(value)
    if number is None or int(number) != number:
        return None
    return int(number)


def _power_kw(node: dict, key: str) -> float | None:
    branch = node.get(key) if isinstance(node, dict) else None
    power = branch.get("power") if isinstance(branch, dict) else None
    if not isinstance(power, dict):
        return None
    value = _number(power.get("value"))
    if value is None or value < 0:
        return None
    unit = str(power.get("unit", "")).strip().lower()
    if unit == "w":
        return value / 1000
    if unit == "kw":
        return value
    return None


def parse_frame(frame: object, received_at_ms: int, settings: Settings) -> ParseResult:
    if not isinstance(frame, dict):
        return ParseResult(None, "invalid_frame")
    errno = _code(frame.get("errno"))
    if errno != 0:
        return ParseResult(None, "upstream_error")
    result = frame.get("result")
    if not isinstance(result, dict):
        return ParseResult(None, "invalid_result")
    time_diff = _number(result.get("timeDiff"))
    if time_diff is None:
        return ParseResult(None, "timediff_missing")
    if time_diff > settings.fresh_timediff_max:
        return ParseResult(None, "stale", time_diff)
    if time_diff < 0:
        return ParseResult(None, "invalid_timediff", time_diff)

    source_epoch_ms = _code(result.get("consumeTs"))
    if not source_epoch_ms:
        return ParseResult(None, "cached", time_diff)
    # Reject seconds, corrupt clocks, and implausibly future upstream timestamps.
    if source_epoch_ms < 1_577_836_800_000 or source_epoch_ms > received_at_ms + 300_000:
        return ParseResult(None, "invalid_source_timestamp", time_diff)

    node = result.get("node")
    if not isinstance(node, dict):
        return ParseResult(None, "invalid_node", time_diff)
    pv = _power_kw(node, "solar")
    load = _power_kw(node, "load")
    grid_magnitude = _power_kw(node, "grid")
    battery_magnitude = _power_kw(node, "bat")
    battery = node.get("bat") if isinstance(node.get("bat"), dict) else {}
    grid = node.get("grid") if isinstance(node.get("grid"), dict) else {}
    soc = _number(battery.get("soc"))
    if soc is not None and not 0 <= soc <= 100:
        soc = None
    if all(value is None for value in (pv, load, grid_magnitude, battery_magnitude, soc)):
        return ParseResult(None, "no_telemetry", time_diff)

    grid_direction = _code(grid.get("gridToHidden"))
    grid_signed = grid_import = grid_export = None
    if grid_magnitude is not None:
        if grid_direction == settings.grid_import_code:
            grid_signed, grid_import, grid_export = grid_magnitude, grid_magnitude, 0.0
        elif grid_direction == settings.grid_export_code:
            grid_signed, grid_import, grid_export = -grid_magnitude, 0.0, grid_magnitude
        elif grid_direction == 0 and grid_magnitude == 0:
            grid_signed = grid_import = grid_export = 0.0

    battery_direction = _code(battery.get("charge"))
    battery_signed = battery_charge = battery_discharge = None
    if battery_magnitude is not None:
        if battery_direction == settings.battery_charge_code:
            battery_signed, battery_charge, battery_discharge = battery_magnitude, battery_magnitude, 0.0
        elif battery_direction == settings.battery_discharge_code:
            battery_signed, battery_charge, battery_discharge = -battery_magnitude, 0.0, battery_magnitude
        elif battery_magnitude == 0:
            battery_signed = battery_charge = battery_discharge = 0.0

    sample = TelemetrySample(
        source_epoch_ms=source_epoch_ms,
        received_at_ms=received_at_ms,
        time_diff_seconds=time_diff,
        pv_power_kw=pv,
        load_power_kw=load,
        grid_power_kw=grid_signed,
        grid_import_power_kw=grid_import,
        grid_export_power_kw=grid_export,
        battery_power_kw=battery_signed,
        battery_charge_power_kw=battery_charge,
        battery_discharge_power_kw=battery_discharge,
        battery_soc_pct=soc,
        grid_direction_code=grid_direction,
        battery_direction_code=battery_direction,
        work_mode=str(result.get("workMode") or "") or None,
    )
    return ParseResult(sample, "fresh", time_diff)

