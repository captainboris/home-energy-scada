"""Normalised telemetry model. All power values use kW."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class TelemetrySample:
    source_epoch_ms: int
    received_at_ms: int
    time_diff_seconds: float
    pv_power_kw: float | None
    load_power_kw: float | None
    grid_power_kw: float | None
    grid_import_power_kw: float | None
    grid_export_power_kw: float | None
    battery_power_kw: float | None
    battery_charge_power_kw: float | None
    battery_discharge_power_kw: float | None
    battery_soc_pct: float | None
    grid_direction_code: int | None
    battery_direction_code: int | None
    work_mode: str | None = None
    source: str = "foxess_ws"

    def identity(self) -> int:
        return self.source_epoch_ms

    def item(self, site_id: str, timezone_name: str) -> dict:
        local = datetime.fromtimestamp(
            self.source_epoch_ms / 1000, ZoneInfo(timezone_name)
        )
        utc = datetime.fromtimestamp(self.source_epoch_ms / 1000, UTC)
        values = asdict(self)
        return {
            "pk": f"SITE#{site_id}#DAY#{local.date().isoformat()}",
            "sk": f"TS#{self.source_epoch_ms:013d}",
            "source_timestamp": utc.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "timestamp_local": local.isoformat(timespec="milliseconds"),
            "received_at": datetime.fromtimestamp(self.received_at_ms / 1000, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            **values,
        }


POWER_METRICS = (
    "pv_power_kw",
    "load_power_kw",
    "grid_import_power_kw",
    "grid_export_power_kw",
    "battery_charge_power_kw",
    "battery_discharge_power_kw",
    "battery_soc_pct",
)

