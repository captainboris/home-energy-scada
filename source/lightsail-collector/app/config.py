"""Runtime configuration loaded from a root-owned systemd environment file."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


class ConfigError(ValueError):
    """Raised when a required setting is absent or unsafe."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is required")
    return value


def _integer(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer") from exc
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, repr=False)
class Settings:
    foxess_email: str
    foxess_password_md5: str
    foxess_plant_id: str | None
    signature_wasm: Path
    table_name: str
    site_id: str
    aws_region: str
    timezone: str = "Australia/Melbourne"
    fresh_timediff_max: int = 30
    stale_after_seconds: int = 35
    reconnect_after_seconds: int = 90
    recovery_probe_seconds: int = 30
    max_session_seconds: int = 480
    queue_size: int = 512
    health_write_seconds: int = 60
    dedupe_capacity: int = 50_000
    battery_charge_code: int = 1
    battery_discharge_code: int = 2
    grid_import_code: int = 1
    grid_export_code: int = -1
    debug_frames: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        password_md5 = os.environ.get("FOXESS_PASSWORD_MD5", "").strip().lower()
        password = os.environ.get("FOXESS_PASSWORD", "")
        if password and password_md5:
            raise ConfigError("set only FOXESS_PASSWORD_MD5 or FOXESS_PASSWORD")
        if password:
            password_md5 = hashlib.md5(password.encode("utf-8")).hexdigest()
        if len(password_md5) != 32 or any(c not in "0123456789abcdef" for c in password_md5):
            raise ConfigError("FOXESS_PASSWORD_MD5 must be a 32-character lowercase MD5 value")

        wasm = Path(_required("FOXESS_SIGNATURE_WASM"))
        if not wasm.is_file():
            raise ConfigError("FOXESS_SIGNATURE_WASM does not point to a readable file")
        site_id = os.environ.get("SITE_ID", "home").strip()
        if not site_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in site_id):
            raise ConfigError("SITE_ID contains unsupported characters")
        return cls(
            foxess_email=_required("FOXESS_EMAIL"),
            foxess_password_md5=password_md5,
            foxess_plant_id=os.environ.get("FOXESS_PLANT_ID", "").strip() or None,
            signature_wasm=wasm,
            table_name=_required("TELEMETRY_TABLE_NAME"),
            site_id=site_id,
            aws_region=os.environ.get("AWS_REGION", "ap-southeast-2").strip(),
            timezone=os.environ.get("DISPLAY_TIMEZONE", "Australia/Melbourne").strip(),
            fresh_timediff_max=_integer("FRESH_TIMEDIFF_MAX", 30, 5, 300),
            stale_after_seconds=_integer("STALE_AFTER_SECONDS", 35, 20, 600),
            reconnect_after_seconds=_integer("RECONNECT_AFTER_SECONDS", 90, 45, 1800),
            recovery_probe_seconds=_integer("RECOVERY_PROBE_SECONDS", 30, 10, 300),
            max_session_seconds=_integer("MAX_SESSION_SECONDS", 480, 120, 7200),
            queue_size=_integer("WRITE_QUEUE_SIZE", 512, 32, 10000),
            health_write_seconds=_integer("HEALTH_WRITE_SECONDS", 60, 15, 600),
            dedupe_capacity=_integer("DEDUPE_CAPACITY", 50_000, 1000, 500_000),
            battery_charge_code=_integer("BATTERY_CHARGE_CODE", 1, -10, 10),
            battery_discharge_code=_integer("BATTERY_DISCHARGE_CODE", 2, -10, 10),
            grid_import_code=_integer("GRID_IMPORT_CODE", 1, -10, 10),
            grid_export_code=_integer("GRID_EXPORT_CODE", -1, -10, 10),
            debug_frames=os.environ.get("DEBUG_FRAMES", "false").strip().lower() == "true",
        )

    def __repr__(self) -> str:
        return (
            "Settings(site_id={!r}, table_name={!r}, aws_region={!r}, timezone={!r})"
            .format(self.site_id, self.table_name, self.aws_region, self.timezone)
        )

