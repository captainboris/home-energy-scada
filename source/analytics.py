"""Daily analytics derived from raw historian rows and FoxESS energy reports.

Raw rows remain the source of truth for power, peaks, behaviour and coverage.
FoxESS report values are preferred for energy totals because they are produced
by the upstream energy counters rather than reconstructed from sampled power.
"""
import math
from datetime import date, datetime, time as daytime, timedelta
from decimal import Decimal

from common import AppError, GAP_SECONDS, METRICS, ZONE, iso

SUMMARY_SCHEMA_VERSION = 1
RAW_INTERVAL_SECONDS = 300

# This is the only FoxESS-specific energy mapping in the application.
REPORT_VARIABLES = {
    'PVEnergyTotal': 'pv_kwh',
    'loads': 'load_kwh',
    'gridConsumption': 'grid_import_kwh',
    'feedin': 'grid_export_kwh',
    'chargeEnergyToTal': 'battery_charge_kwh',
    'dischargeEnergyToTal': 'battery_discharge_kwh',
}

POWER_FALLBACKS = {
    'pv_kwh': 'pv_power_kw',
    'load_kwh': 'load_power_kw',
    'grid_import_kwh': 'grid_import_power_kw',
    'grid_export_kwh': 'grid_export_power_kw',
    'battery_charge_kwh': 'battery_charge_power_kw',
    'battery_discharge_kwh': 'battery_discharge_power_kw',
}


def finite_number(value, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= minimum else None


def day_bounds(day):
    if isinstance(day, str):
        day = date.fromisoformat(day)
    start = datetime.combine(day, daytime.min, ZONE)
    end = datetime.combine(day + timedelta(days=1), daytime.min, ZONE)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def local_days_for_window(start_epoch, end_epoch):
    """Return Melbourne dates touched by the half-open epoch-second window."""
    if end_epoch <= start_epoch:
        return []
    first = datetime.fromtimestamp(start_epoch, ZONE).date()
    last = datetime.fromtimestamp(max(start_epoch, end_epoch - 0.001), ZONE).date()
    days = []
    cursor = first
    while cursor <= last:
        days.append(cursor)
        cursor += timedelta(days=1)
    return days


def normalise_report(payload, fetched_at=None):
    """Validate a dimension=day report and retain its 24 hourly buckets."""
    if not isinstance(payload, dict) or str(payload.get('errno')) != '0':
        code = str(payload.get('errno', 'unknown')) if isinstance(payload, dict) else 'invalid'
        raise AppError(502, 'FOX_REPORT_ERROR', f'Fox 日报返回错误码 {code[:12]}。')
    rows = payload.get('result')
    if not isinstance(rows, list):
        raise AppError(502, 'FOX_REPORT_FORMAT', 'Fox 日报结构与预期不同。')
    by_variable = {row.get('variable'): row for row in rows if isinstance(row, dict)}
    energy, hourly = {}, {}
    for fox_name, metric in REPORT_VARIABLES.items():
        row = by_variable.get(fox_name)
        if not isinstance(row, dict) or str(row.get('unit', '')).strip().lower() != 'kwh':
            continue
        values = row.get('values')
        if not isinstance(values, list) or not values:
            continue
        buckets = [finite_number(value) for value in values[:24]]
        if len(buckets) < 24:
            buckets.extend([None] * (24 - len(buckets)))
        valid = [value for value in buckets if value is not None]
        if valid:
            hourly[metric] = buckets
            energy[metric] = round(sum(valid), 6)
    if not energy:
        raise AppError(502, 'FOX_REPORT_FORMAT', 'Fox 日报没有可用的 kWh 指标。')
    return {'energy': energy, 'hourly': hourly, 'fetched_at': int(fetched_at or datetime.now().timestamp()),
            'source': 'foxess_report_hourly'}


def normalise_reserve_soc(payload):
    if not isinstance(payload, dict) or str(payload.get('errno')) != '0' or not isinstance(payload.get('result'), dict):
        raise AppError(502, 'FOX_RESERVE_ERROR', 'Fox 没有返回有效的电池 reserve 设置。')
    value = finite_number(payload['result'].get('minSocOnGrid'))
    if value is None or value > 100:
        raise AppError(502, 'FOX_RESERVE_FORMAT', 'Fox 返回的 minSocOnGrid 无效。')
    return value


def integrate_power(rows, metric, start_ms, end_ms):
    points = []
    for row in rows:
        stamp = int(row.get('epoch_ms', 0))
        value = finite_number(row.get(metric))
        if start_ms <= stamp < end_ms and value is not None:
            points.append((stamp, value))
    points.sort()
    total = 0.0
    for (left_t, left_v), (right_t, right_v) in zip(points, points[1:]):
        seconds = (right_t - left_t) / 1000
        if 0 < seconds <= GAP_SECONDS:
            total += (left_v + right_v) * 0.5 * seconds / 3600
    return round(total, 6) if len(points) >= 2 else None


def counter_at(rows, metric, target_ms):
    """Interpolate a cumulative register at a boundary bracketed by raw points."""
    points = sorted((int(row.get('epoch_ms', 0)), finite_number(row.get(metric))) for row in rows)
    points = [(stamp, value) for stamp, value in points if value is not None]
    before = next(((stamp, value) for stamp, value in reversed(points) if stamp <= target_ms), None)
    after = next(((stamp, value) for stamp, value in points if stamp >= target_ms), None)
    if before and before[0] == target_ms:
        return before[1]
    if not before or not after or before[0] == after[0]:
        return None
    if target_ms - before[0] > GAP_SECONDS * 1000 or after[0] - target_ms > GAP_SECONDS * 1000:
        return None
    if after[1] < before[1]:
        return None
    ratio = (target_ms - before[0]) / (after[0] - before[0])
    return before[1] + (after[1] - before[1]) * ratio


def counter_delta(rows, metric, start_ms, end_ms):
    if end_ms <= start_ms:
        return None
    start_value, end_value = counter_at(rows, metric, start_ms), counter_at(rows, metric, end_ms)
    if start_value is None or end_value is None or end_value < start_value:
        return None
    return round(end_value - start_value, 6)


def peak(rows, metric):
    winner = None
    for row in rows:
        value = finite_number(row.get(metric))
        if value is None:
            continue
        if winner is None or value > winner[0]:
            winner = (value, row.get('timestamp_local'))
    return {'kw': round(winner[0], 3), 'time': winner[1]} if winner else {'kw': None, 'time': None}


def reserve_reached(rows, reserve_soc_pct):
    reserve = finite_number(reserve_soc_pct)
    if reserve is None:
        return None
    was_above = False
    for row in sorted(rows, key=lambda item: int(item.get('epoch_ms', 0))):
        value = finite_number(row.get('battery_soc_pct'))
        if value is None:
            continue
        if value > reserve:
            was_above = True
        elif was_above:
            return row.get('timestamp_local')
    return None


def coverage(rows, start_ms, end_ms, now_ms):
    cutoff = min(end_ms, max(start_ms, int(now_ms)))
    elapsed = max(0, cutoff - start_ms)
    expected = math.ceil(elapsed / (RAW_INTERVAL_SECONDS * 1000)) if elapsed else 0
    metrics = [metric for metric, _unit in METRICS.values()]
    observed = {
        int(row.get('epoch_ms', 0)) for row in rows
        if start_ms <= int(row.get('epoch_ms', 0)) < cutoff
        and any(finite_number(row.get(metric)) is not None for metric in metrics)
    }
    pct = min(100.0, 100 * len(observed) / expected) if expected else 0.0
    return round(pct, 1), len(observed), expected


def build_daily_summary(day, rows, now_epoch, report=None, previous=None,
                        reserve_soc_pct=None, reserve_source='configured_fallback'):
    """Build an overwriteable summary item for one Melbourne calendar day."""
    day = date.fromisoformat(day) if isinstance(day, str) else day
    start_ms, end_ms = day_bounds(day)
    now_ms = int(now_epoch * 1000)
    effective_end = min(end_ms, max(start_ms, now_ms + 1))
    cached_report = report or ((previous or {}).get('_report') if previous else None)
    report_energy = cached_report.get('energy', {}) if isinstance(cached_report, dict) else {}
    energy, energy_sources = {}, {}
    for metric, power_metric in POWER_FALLBACKS.items():
        official = finite_number(report_energy.get(metric))
        if official is not None:
            energy[metric] = round(official, 3)
            energy_sources[metric] = 'foxess_report_hourly'
        else:
            energy[metric] = integrate_power(rows, power_metric, start_ms, effective_end)
            energy_sources[metric] = 'raw_power_integration'

    load = energy.get('load_kwh')
    grid_import = energy.get('grid_import_kwh')
    self_sufficiency = None
    if load is not None and grid_import is not None and load > 0:
        self_sufficiency = round((1 - grid_import / load) * 100, 1)

    hourly_grid = cached_report.get('hourly', {}).get('grid_import_kwh') if isinstance(cached_report, dict) else None
    if isinstance(hourly_grid, list) and len(hourly_grid) >= 21 and all(finite_number(v) is not None for v in hourly_grid[18:21]):
        peak_period = round(sum(float(v) for v in hourly_grid[18:21]), 3)
        peak_period_source = 'foxess_report_hourly'
    else:
        peak_start = int(datetime.combine(day, daytime(18), ZONE).timestamp() * 1000)
        peak_end = int(datetime.combine(day, daytime(21), ZONE).timestamp() * 1000)
        interval_end = min(peak_end, effective_end)
        peak_period = counter_delta(rows, 'grid_import_energy_total_kwh', peak_start, interval_end)
        peak_period_source = 'foxess_cumulative_counter'
        if peak_period is None:
            peak_period = integrate_power(rows, 'grid_import_power_kw', peak_start, interval_end)
            peak_period_source = 'raw_power_integration'

    raw_coverage, raw_samples, expected_samples = coverage(rows, start_ms, end_ms, now_ms)
    summary = {
        'summary_schema_version': SUMMARY_SCHEMA_VERSION,
        'date': day.isoformat(),
        'timezone': 'Australia/Melbourne',
        'computed_at': iso(now_epoch),
        'energy': energy,
        'performance': {'self_sufficiency_pct': self_sufficiency},
        'peaks': {
            'pv': peak(rows, 'pv_power_kw'),
            'load': peak(rows, 'load_power_kw'),
            'grid_import': peak(rows, 'grid_import_power_kw'),
            'grid_export': peak(rows, 'grid_export_power_kw'),
        },
        'battery': {
            'reserve_soc_pct': finite_number(reserve_soc_pct),
            'reserve_reached_time': reserve_reached(rows, reserve_soc_pct),
        },
        'peak_period': {'grid_import_18_21_kwh': peak_period},
        'data_quality': {
            'raw_coverage_pct': raw_coverage,
            'raw_samples': raw_samples,
            'expected_samples': expected_samples,
        },
        'metric_sources': {
            'energy': energy_sources,
            'self_sufficiency_pct': 'derived_from_energy',
            'peaks': 'raw_historian',
            'battery_reserve': reserve_source,
            'grid_import_18_21_kwh': peak_period_source,
            'raw_coverage_pct': 'raw_historian',
        },
    }
    if cached_report:
        summary['_report'] = cached_report
    return summary


def public_summary(item):
    if not item:
        return None
    return {key: value for key, value in item.items() if key not in {'pk', 'sk'} and not key.startswith('_')}
