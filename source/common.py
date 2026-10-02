"""Shared units and Fox timestamp parsing. No network requests at import time."""
import math
import re
import hashlib
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

METRICS = {
    "pvPower": ("pv_power_kw", "kW"),
    "loadsPower": ("load_power_kw", "kW"),
    "gridConsumptionPower": ("grid_import_power_kw", "kW"),
    "feedinPower": ("grid_export_power_kw", "kW"),
    "batChargePower": ("battery_charge_power_kw", "kW"),
    "batDischargePower": ("battery_discharge_power_kw", "kW"),
    "SoC": ("battery_soc_pct", "%"),
}
ENERGY_COUNTERS = {
    "PVEnergyTotal": ("pv_energy_total_kwh", "kWh"),
    "loads": ("load_energy_total_kwh", "kWh"),
    "gridConsumption": ("grid_import_energy_total_kwh", "kWh"),
    "feedin": ("grid_export_energy_total_kwh", "kWh"),
    "chargeEnergyToTal": ("battery_charge_energy_total_kwh", "kWh"),
    "dischargeEnergyToTal": ("battery_discharge_energy_total_kwh", "kWh"),
}
# The Overview still exposes only METRICS. Counters are collected in the same
# history request so analytics can use an official register before integrating
# sampled power, without consuming another Fox API call.
HISTORY_VARIABLES = {**METRICS, **ENERGY_COUNTERS}
ZONE = ZoneInfo("Australia/Melbourne")
VERSION = "0.4.1"
GAP_SECONDS = 600


class AppError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message

def iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")

def parse_fox_time(value, naive_timezone="UTC"):
    """Accept explicit offsets including '2026-09-16 00:02:17 AEST+1000'.

    Offset-bearing data wins over any named timezone. Fox documents naive times as UTC;
    an optional deployment setting can override this only after checking actual data.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        stamp = float(value)
        if not math.isfinite(stamp):
            raise ValueError("non-finite time")
        return stamp / 1000 if abs(stamp) >= 100_000_000_000 else stamp
    if not isinstance(value, str):
        raise ValueError("invalid time")
    text = value.strip()
    text = re.sub(r"\s+[A-Za-z_]+([+-]\d{2}:?\d{2})$", r"\1", text)
    if text.endswith(" UTC"):
        text = text[:-4] + "+00:00"
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        # A local wall-clock time during DST fallback is ambiguous; don't guess it.
        zone = ZoneInfo(naive_timezone)
        first, second = parsed.replace(tzinfo=zone, fold=0), parsed.replace(tzinfo=zone, fold=1)
        if first.utcoffset() != second.utcoffset():
            raise ValueError("ambiguous local time")
        parsed = first
    return parsed.timestamp()

def normalise_history(payload, sn, start, end, naive_timezone="UTC"):
    if not isinstance(payload, dict) or str(payload.get("errno")) != "0":
        code = str(payload.get("errno", "unknown")) if isinstance(payload, dict) else "invalid"
        # Do not reflect upstream bodies, credentials, or raw device identifiers.
        safe_code = code if re.fullmatch(r"[0-9-]{1,12}", code) else "unknown"
        raise AppError(502, "FOX_API_ERROR", f"Fox 返回错误码 {safe_code}。请核对 API key、逆变器序列号和调用额度。")
    devices = payload.get("result")
    if not isinstance(devices, list):
        raise AppError(502, "FOX_RESPONSE_FORMAT", "Fox 返回的数据结构与预期不同。")
    selected = [d for d in devices if isinstance(d, dict) and d.get("deviceSN") == sn]
    if not selected:
        if not devices:
            selected = [{"datas": []}]
        else:
            raise AppError(502, "FOX_DEVICE_NOT_FOUND", "响应中没有配置的逆变器，请确认使用逆变器 SN，而非采集器或电池 SN。")
    rows = selected[0].get("datas", [])
    if not isinstance(rows, list):
        raise AppError(502, "FOX_RESPONSE_FORMAT", "Fox 的 datas 字段格式与预期不同。")
    by_variable = {row.get("variable"): row for row in rows if isinstance(row, dict)}
    series, invalid, time_errors, missing = [], 0, 0, []
    for variable, (metric, expected_unit) in HISTORY_VARIABLES.items():
        row = by_variable.get(variable, {})
        unit = str(row.get("unit", "")).strip().lower()
        scale = 0.001 if expected_unit == "kW" and unit == "w" else 1.0
        compatible = unit in ({"kw", "w"} if expected_unit == "kW" else
                              {"%", "percent"} if expected_unit == "%" else {"kwh"})
        values = row.get("data", [])
        if not isinstance(values, list):
            values = []
        samples = {}
        for sample in values[:10000]:
            if not isinstance(sample, dict):
                time_errors += 1
                continue
            try:
                stamp = parse_fox_time(sample.get("time"), naive_timezone)
                if not start <= stamp < end:
                    continue
            except (ValueError, TypeError, OverflowError):
                time_errors += 1
                continue
            raw_value = sample.get("value")
            quality = "missing" if raw_value is None else "good"
            try:
                if raw_value is None or isinstance(raw_value, bool) or not compatible:
                    raise ValueError("missing value or unsupported unit")
                value = float(raw_value) * scale
                if not math.isfinite(value) or value < 0 or (expected_unit == "%" and value > 100):
                    raise ValueError("invalid value")
            except (ValueError, TypeError):
                value = None
                quality = "missing" if raw_value is None else "invalid"
                invalid += quality == "invalid"
            if value is not None or samples.get(stamp, {}).get('value') is None:
                samples[stamp] = {"timestamp": iso(stamp), "value": value, "quality": quality}
        points = [samples[t] for t in sorted(samples)]
        if not points and variable in METRICS:
            missing.append(metric)
        series.append({"metric": metric, "unit": expected_unit, "points": points})
    warnings = []
    if missing:
        warnings.append("部分指标没有返回数据：" + ", ".join(missing))
    if invalid:
        warnings.append(f"{invalid} 个无效读数或单位不匹配的读数已显示为缺失，未填成 0。")
    if time_errors:
        warnings.append(f"{time_errors} 个无法可靠解析时间的点已跳过。")
    return series, warnings

def fox_signature(path, token, timestamp):
    # Fox's official Python example uses literal backslash-r/backslash-n, not CR/LF bytes.
    material = fr"{path}\r\n{token}\r\n{timestamp}"
    return hashlib.md5(material.encode()).hexdigest()
