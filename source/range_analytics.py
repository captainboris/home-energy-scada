"""Web/API range analytics orchestration; not a REST Collector dependency.

The HTTP entrypoint parses the window/configuration and owns the response.
Fast storage is acquired lazily so legacy-only ranges need no Fast table and
Fast acquisition/read AppErrors retain the existing warning fallback.
"""
import time
from datetime import datetime, time as daytime

from analytics import (POWER_FALLBACKS, coverage, finite_number,
                       local_days_for_window, peak, reserve_reached)
from common import AppError, ZONE, iso
from history_service import boundary_epoch_ms
from telemetry_storage import telemetry_peaks


def day_start_ms(value):
    return int(datetime.combine(value, daytime.min, ZONE).timestamp() * 1000)


PEAK_METRICS = {
    'pv': 'pv_power_kw',
    'load': 'load_power_kw',
    'grid_import': 'grid_import_power_kw',
    'grid_export': 'grid_export_power_kw',
}


def sourced_legacy_peak(rows, metric):
    result = peak(rows, metric)
    return {
        **result,
        'source': 'legacy_rest_5m',
        'sample_resolution_seconds': 300,
    }


def winning_peak(*candidates):
    available = [candidate for candidate in candidates
                 if finite_number((candidate or {}).get('kw')) is not None]
    if not available:
        return next((candidate for candidate in candidates if candidate),
                    {'kw': None, 'time': None, 'source': None,
                     'sample_resolution_seconds': None})
    return max(available, key=lambda candidate: float(candidate['kw']))


def build_range_summary(window, now, store, *, data_start, battery_start,
                        telemetry_store_factory):
    """Return range business data for an already parsed half-open query window.

    Installation dates define expected reports/battery applicability. Today
    may be partial; only missing completed dates generate report warnings.
    checked_at intentionally reads the completion clock rather than now.
    """
    today = datetime.fromtimestamp(now, ZONE).date()
    now_ms = int(now * 1000)
    if window['start_ms'] > now_ms:
        raise AppError(400, 'INVALID_DATE',
                       'Energy Analytics 只能查询今天或过去的时间范围。')

    raw_end_ms = min(window['end_ms'], now_ms + 1)
    selected_days = local_days_for_window(window['start_ms'] / 1000,
                                          raw_end_ms / 1000)
    report_days = [day for day in selected_days if day >= data_start]
    battery_days = [day for day in report_days if day >= battery_start]
    completed_report_days = [day for day in report_days if day < today]

    historian_start_ms = max(window['start_ms'], day_start_ms(data_start))
    rows = (store.query_rows(historian_start_ms, raw_end_ms)
            if historian_start_ms < raw_end_ms else [])
    battery_start_ms = day_start_ms(max(data_start, battery_start))
    battery_rows = [row for row in rows
                    if int(row.get('epoch_ms', 0)) >= battery_start_ms]
    state = store.state()

    boundary_ms = boundary_epoch_ms()
    legacy_peak_rows = [row for row in rows
                        if int(row.get('epoch_ms', 0)) < boundary_ms]
    fast_peak_error = None
    fast_peaks = {}
    fast_start_ms = max(int(window['start_ms']), boundary_ms)
    if fast_start_ms < raw_end_ms:
        try:
            fast_peaks = telemetry_peaks(
                fast_start_ms,
                raw_end_ms,
                tuple(PEAK_METRICS.values()),
                telemetry_store_factory())
        except AppError as exc:
            fast_peak_error = {'code': exc.code, 'message': exc.message}
    range_peaks = {}
    for name, metric in PEAK_METRICS.items():
        candidates = []
        if int(window['start_ms']) < boundary_ms:
            candidates.append(sourced_legacy_peak(legacy_peak_rows, metric))
        if fast_start_ms < raw_end_ms and fast_peaks.get(metric):
            candidates.append(fast_peaks[metric])
        range_peaks[name] = winning_peak(*candidates)

    summaries = []
    summaries_by_day = {}
    for day in report_days:
        item = store.get_summary(day)
        if item:
            summaries.append(item)
            summaries_by_day[day] = item
    missing_summary_days = [day.isoformat() for day in completed_report_days
                            if day not in summaries_by_day]

    energy = {}
    energy_sources = {}
    energy_day_counts = {}
    energy_expected_days = {}
    missing_official_by_metric = {}
    battery_energy_metrics = {'battery_charge_kwh', 'battery_discharge_kwh'}
    for metric in POWER_FALLBACKS:
        metric_days = battery_days if metric in battery_energy_metrics else report_days
        required_days = [day for day in metric_days if day < today]
        official = []
        official_by_day = {}
        for day in metric_days:
            item = summaries_by_day.get(day)
            if not item:
                continue
            source = ((item.get('metric_sources') or {}).get('energy') or {}).get(metric)
            value = finite_number((item.get('energy') or {}).get(metric))
            if source == 'foxess_report_hourly' and value is not None:
                official.append(value)
                official_by_day[day] = value
        energy_day_counts[metric] = len(official)
        energy_expected_days[metric] = len(metric_days)
        missing_completed = [day for day in required_days if day not in official_by_day]
        if missing_completed:
            missing_official_by_metric[metric] = [day.isoformat()
                                                  for day in missing_completed]
            energy[metric] = None
            energy_sources[metric] = 'unavailable_missing_official_report'
        elif official:
            energy[metric] = round(sum(official), 3)
            energy_sources[metric] = 'foxess_report_daily_sum'
        elif not metric_days:
            energy[metric] = None
            energy_sources[metric] = ('not_applicable_before_battery_install'
                if metric in battery_energy_metrics
                else 'not_applicable_before_data_start')
        else:
            # A current-day report may not exist yet; that is normal, not a warning.
            energy[metric] = None
            energy_sources[metric] = 'unavailable_current_report'

    load = energy.get('load_kwh')
    grid_import = energy.get('grid_import_kwh')
    self_sufficiency = None
    if load is not None and grid_import is not None and load > 0:
        self_sufficiency = round((1 - grid_import / load) * 100, 1)

    minimum_soc = None
    for row in battery_rows:
        value = finite_number(row.get('battery_soc_pct'))
        if value is not None and (minimum_soc is None or value < minimum_soc[0]):
            minimum_soc = (value, row.get('timestamp_local'))

    peak_period_values = []
    peak_period_sources = []
    peak_period_by_day = {}
    for day, item in summaries_by_day.items():
        value = finite_number((item.get('peak_period') or {}).get(
            'grid_import_18_21_kwh'))
        if value is not None:
            peak_period_values.append(value)
            peak_period_by_day[day] = value
            peak_period_sources.append((item.get('metric_sources') or {}).get(
                'grid_import_18_21_kwh'))
    missing_peak_period = [day for day in completed_report_days
                           if day not in peak_period_by_day]
    peak_period = (round(sum(peak_period_values), 3)
                   if peak_period_values and not missing_peak_period else None)

    if historian_start_ms < raw_end_ms:
        raw_coverage, raw_samples, expected_samples = coverage(
            rows, historian_start_ms, window['end_ms'], now_ms)
    else:
        raw_coverage, raw_samples, expected_samples = None, 0, 0
    reserve_soc = finite_number(state.get('reserve_soc_pct'))

    warnings = []
    warning_codes = []
    if missing_official_by_metric:
        missing_days = sorted({value for values in missing_official_by_metric.values()
                               for value in values})
        warnings.append('部分已结束日期缺少 FoxESS 官方日报；对应 Energy KPI 暂不显示，且不会用功率积分替代。')
        warning_codes.append({'code': 'OFFICIAL_REPORT_MISSING',
                              'days': missing_days,
                              'metrics': sorted(missing_official_by_metric)})
    if missing_summary_days:
        warnings.append('缺少 Daily Summary：' + ', '.join(missing_summary_days[:8]) +
                        ('…' if len(missing_summary_days) > 8 else ''))
        warning_codes.append({'code': 'SUMMARY_MISSING',
                              'days': missing_summary_days})
    if fast_peak_error:
        warnings.append('Fast Telemetry Peak analytics 暂不可用；未使用 averaged Chart points 代替。')
        warning_codes.append({'code': 'FAST_PEAK_UNAVAILABLE',
                              'detail': fast_peak_error['code']})

    computed = [str(item.get('computed_at')) for item in summaries
                if item.get('computed_at')]
    battery_applicable = bool(battery_days)
    data = {
        'timezone': 'Australia/Melbourne',
        'range': window,
        'availability': {
            'foxess_data_start_date': data_start.isoformat(),
            'battery_install_date': battery_start.isoformat(),
            'data_applicable': bool(report_days),
            'battery_applicable': battery_applicable,
        },
        'report_dates': {
            'start': report_days[0].isoformat() if report_days else None,
            'end': report_days[-1].isoformat() if report_days else None,
            'expected_days': len(report_days),
            'completed_expected_days': len(completed_report_days),
            'complete_summary_days': len(summaries),
            'official_days_by_metric': energy_day_counts,
            'expected_days_by_metric': energy_expected_days,
        },
        'energy': energy,
        'performance': {'self_sufficiency_pct': self_sufficiency},
        'peaks': range_peaks,
        'battery': {
            'applicable': battery_applicable,
            'reserve_soc_pct': reserve_soc if battery_applicable else None,
            'reserve_reached_time': (reserve_reached(battery_rows, reserve_soc)
                                     if battery_applicable else None),
            'minimum_soc_pct': round(minimum_soc[0], 1) if minimum_soc else None,
            'minimum_soc_time': minimum_soc[1] if minimum_soc else None,
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
            'peaks': ('hybrid_real_samples_or_rollup_max' if report_days else
                      'not_applicable_before_data_start'),
            'peak_sources': {name: item.get('source')
                             for name, item in range_peaks.items()},
            'minimum_soc': ('raw_historian' if battery_applicable else
                            'not_applicable_before_battery_install'),
            'battery_reserve': (state.get('reserve_source', 'configured_fallback')
                                if battery_applicable else
                                'not_applicable_before_battery_install'),
            'grid_import_18_21_kwh': ('daily_summary_sum' if peak_period is not None
                                      else 'unavailable'),
            'grid_import_18_21_daily_sources': peak_period_sources,
            'raw_coverage_pct': ('raw_historian' if expected_samples else
                                 'not_applicable_before_data_start'),
        },
        'computed_at': max(computed) if computed else None,
        'checked_at': iso(time.time()),
        'warnings': warnings,
        'warning_codes': warning_codes,
    }
    return data
