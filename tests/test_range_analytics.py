"""Range orchestration contract with existing report/telemetry fixtures; no IO."""
import os
import unittest
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import Mock, patch

import lambda_function as web
from analytics import POWER_FALLBACKS, build_daily_summary
from common import AppError, ZONE, iso
from test_backend import decode, event
from test_fast_telemetry import FakeStore as FastStore, minute, raw


NOW = datetime(2026, 10, 6, 12, tzinfo=ZONE).timestamp()


def epoch(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=ZONE).timestamp() * 1000)


def official(day, now=NOW, value=1.23456):
    return build_daily_summary(date.fromisoformat(day), [], now, report={
        'energy': {metric: value for metric in POWER_FALLBACKS},
        'hourly': {'grid_import_kwh': [0] * 24},
        'source': 'foxess_report_hourly'}, reserve_soc_pct=40)


class LegacyStore:
    def __init__(self, rows=(), summaries=None):
        self.rows = list(rows)
        self.summaries = summaries or {}
        self.query_rows = Mock(side_effect=lambda start, end: [
            row for row in self.rows if start <= row['epoch_ms'] < end])
        self.state = Mock(return_value={'reserve_soc_pct': 40,
                                        'reserve_source': 'configured_fallback'})
        self.get_summary = Mock(side_effect=lambda day: self.summaries.get(day.isoformat()))


class RangeAnalyticsTests(unittest.TestCase):
    def setUp(self):
        self.now = NOW
        self.store = LegacyStore()
        self.fast = FastStore()
        self.env = patch.dict(os.environ, {
            'APP_PASSWORD': '1234567890', 'FOXESS_DATA_START_DATE': '2026-09-30',
            'BATTERY_INSTALL_DATE': '2026-10-01', 'FAST_TELEMETRY_START_DATE': '2026-10-01'})
        self.env.start(); self.addCleanup(self.env.stop)
        self.clock = patch('time.time', side_effect=lambda: self.now)
        self.clock.start(); self.addCleanup(self.clock.stop)
        self.factory = Mock(side_effect=lambda: self.fast)
        self.request_params = None

    def call(self, start, end, preset='other'):
        self.request_params = {'range': preset, 'from_ms': str(epoch(start)), 'to_ms': str(epoch(end))}
        with patch.object(web, 'get_store', return_value=self.store), \
                patch.object(web, 'get_telemetry_store', self.factory), \
                patch.object(web, 'require_session', return_value=('session', {})), \
                patch('builtins.print'):
            self.result = web.lambda_handler(event('/api/summary/range', query=self.request_params),
                                             SimpleNamespace(aws_request_id='range-contract'))
        self.assertEqual(self.result['headers']['Cache-Control'], 'no-store')
        self.assertEqual(self.result['headers']['Content-Type'], 'application/json; charset=utf-8')
        self.assertEqual(self.result['headers']['X-Request-ID'], 'range-contract')
        return decode(self.result)

    def data(self, start, end, preset='other'):
        body = self.call(start, end, preset)
        self.assertEqual(self.result['statusCode'], 200, body)
        return body['data']

    def test_before_installation_does_not_query_or_initialize_fast_store(self):
        self.factory.side_effect = AssertionError('legacy must not initialize Fast storage')
        data = self.data('2026-09-28', '2026-09-30')
        self.store.query_rows.assert_not_called(); self.store.get_summary.assert_not_called()
        self.factory.assert_not_called()
        self.assertEqual(data['warnings'], [])
        self.assertEqual(data['report_dates']['expected_days'], 0)
        self.assertIsNone(data['data_quality']['raw_coverage_pct'])
        self.assertTrue(all(value is None for value in data['energy'].values()))
        self.assertFalse(data['availability']['data_applicable'])
        self.assertFalse(data['battery']['applicable'])

    def test_data_and_battery_installation_boundaries_and_zero(self):
        self.store.summaries = {day: official(day, value=0) for day in ['2026-09-30', '2026-10-01']}
        low_at = epoch('2026-10-01')
        self.store.rows = [
            {'epoch_ms': low_at - 1, 'battery_soc_pct': 1, 'timestamp_local': iso((low_at - 1) / 1000)},
            {'epoch_ms': low_at, 'battery_soc_pct': 0, 'timestamp_local': iso(low_at / 1000)}]
        data = self.data('2026-09-29', '2026-10-02')
        self.store.query_rows.assert_called_once_with(epoch('2026-09-30'), epoch('2026-10-02'))
        self.assertEqual(data['report_dates']['expected_days'], 2)
        self.assertEqual(data['report_dates']['expected_days_by_metric']['battery_charge_kwh'], 1)
        self.assertEqual(data['energy']['battery_charge_kwh'], 0)
        self.assertEqual(data['battery']['minimum_soc_pct'], 0)
        self.assertEqual(data['battery']['minimum_soc_time'], iso(low_at / 1000))
        self.assertIsNone(data['performance']['self_sufficiency_pct'])
        self.assertEqual(data['peak_period']['grid_import_18_21_kwh'], 0)
        self.assertEqual(data['warnings'], [])

    def test_battery_metrics_remain_inapplicable_on_day_before_install(self):
        self.store.summaries = {'2026-09-30': official('2026-09-30')}
        data = self.data('2026-09-30', '2026-10-01')
        self.assertEqual(data['energy']['pv_kwh'], 1.235)
        self.assertIsNone(data['energy']['battery_charge_kwh'])
        self.assertEqual(data['metric_sources']['energy']['battery_charge_kwh'],
                         'not_applicable_before_battery_install')
        self.assertFalse(data['battery']['applicable'])
        self.factory.assert_not_called()

    def test_partial_today_keeps_full_range_and_no_completed_report_warning(self):
        self.store.summaries = {'2026-10-05': official('2026-10-05')}
        data = self.data('2026-10-05', '2026-10-07', 'week')
        self.store.query_rows.assert_called_once_with(epoch('2026-10-05'), int(NOW * 1000) + 1)
        self.assertEqual(data['range']['end_ms'], epoch('2026-10-07'))
        self.assertEqual(data['report_dates']['expected_days'], 2)
        self.assertEqual(data['report_dates']['completed_expected_days'], 1)
        self.assertEqual(data['energy']['pv_kwh'], 1.235)
        self.assertEqual(data['warnings'], [])
        self.assertEqual(data['warning_codes'], [])

    def test_today_without_report_is_null_not_zero_or_a_missing_warning(self):
        data = self.data('2026-10-06', '2026-10-07', 'day')
        self.assertIsNone(data['energy']['load_kwh'])
        self.assertEqual(data['metric_sources']['energy']['load_kwh'], 'unavailable_current_report')
        self.assertEqual(data['warning_codes'], [])

    def test_completed_fallback_and_absent_summary_do_not_replace_official_energy(self):
        self.store.summaries = {'2026-10-03': official('2026-10-03'),
                               '2026-10-04': build_daily_summary(date(2026, 10, 4), [], NOW)}
        data = self.data('2026-10-03', '2026-10-06')
        self.assertIsNone(data['energy']['pv_kwh'])
        self.assertEqual(data['metric_sources']['energy']['pv_kwh'], 'unavailable_missing_official_report')
        codes = {warning['code']: warning for warning in data['warning_codes']}
        self.assertEqual(codes['OFFICIAL_REPORT_MISSING']['days'], ['2026-10-04', '2026-10-05'])
        self.assertEqual(codes['SUMMARY_MISSING']['days'], ['2026-10-05'])
        self.assertIsNone(data['peak_period']['grid_import_18_21_kwh'])

    def test_cross_source_peaks_keep_winning_value_source_time_and_legacy_tie(self):
        legacy_at = epoch('2026-09-30') + 5000
        fast_at = epoch('2026-10-01') + 5000
        self.store.rows = [{'epoch_ms': legacy_at, 'timestamp_local': iso(legacy_at / 1000),
                           'pv_power_kw': 2, 'load_power_kw': 10, 'grid_import_power_kw': 0,
                           'grid_export_power_kw': 0}]
        self.fast = FastStore(raw=[raw(fast_at, 8)])
        data = self.data('2026-09-30', '2026-10-02')
        self.assertEqual(data['peaks']['pv'], {'kw': 8, 'time': iso(fast_at / 1000),
                         'source': 'fast_telemetry_raw', 'sample_resolution_seconds': 5})
        self.assertEqual(data['peaks']['load'], {'kw': 10, 'time': iso(legacy_at / 1000),
                         'source': 'legacy_rest_5m', 'sample_resolution_seconds': 300})
        self.assertEqual(data['peaks']['grid_import']['kw'], 0)
        self.assertEqual(data['peaks']['grid_import']['source'], 'legacy_rest_5m')

    def test_dst_day_keeps_23_hour_window_and_query_coverage(self):
        data = self.data('2026-10-04', '2026-10-05', 'day')
        self.assertEqual(data['range']['end_ms'] - data['range']['start_ms'], 23 * 3600000)
        self.assertTrue(data['range']['start_at'].endswith('+10:00'))
        self.assertTrue(data['range']['end_at'].endswith('+11:00'))
        self.assertEqual(data['data_quality']['expected_samples'], 23 * 12)
        self.store.query_rows.assert_called_once_with(epoch('2026-10-04'), epoch('2026-10-05'))

    def test_long_fast_range_uses_rollup_max_not_average_with_real_peak_time(self):
        bucket = epoch('2026-10-01') + 60000
        self.fast = FastStore(rollups=[minute(bucket, maximum=8, average=2)])
        data = self.data('2026-10-01', '2026-11-01', 'month')
        self.assertEqual(data['peaks']['load'], {'kw': 8, 'time': iso((bucket + 45000) / 1000),
                         'source': 'fast_telemetry_rollup_max', 'sample_resolution_seconds': 60})

    def test_fast_store_configuration_error_remains_warning_with_legacy_peak(self):
        stamp = epoch('2026-09-30') + 5000
        self.store.rows = [{'epoch_ms': stamp, 'timestamp_local': iso(stamp / 1000), 'pv_power_kw': 3.2}]
        self.factory.side_effect = AppError(503, 'TELEMETRY_NOT_CONFIGURED', 'missing Fast table')
        data = self.data('2026-09-30', '2026-10-02')
        self.assertEqual(data['peaks']['pv']['kw'], 3.2)
        self.assertIsNone(data['peaks']['load']['kw'])
        self.assertIn({'code': 'FAST_PEAK_UNAVAILABLE', 'detail': 'TELEMETRY_NOT_CONFIGURED'}, data['warning_codes'])

    def test_fast_read_error_remains_warning_and_null_peaks(self):
        self.fast.query = Mock(side_effect=AppError(503, 'TELEMETRY_READ_FAILED', 'read unavailable'))
        data = self.data('2026-10-01', '2026-10-02')
        self.assertTrue(all(peak['kw'] is None for peak in data['peaks'].values()))
        self.assertIn({'code': 'FAST_PEAK_UNAVAILABLE', 'detail': 'TELEMETRY_READ_FAILED'}, data['warning_codes'])

    def test_checked_at_reads_completion_clock_not_request_now(self):
        def delayed_state():
            self.now += 17
            return {'reserve_soc_pct': 40}
        self.store.state.side_effect = delayed_state
        data = self.data('2026-09-30', '2026-10-01')
        self.assertEqual(data['checked_at'], iso(NOW + 17))
        self.assertEqual(data['range']['end_ms'], epoch('2026-10-01'))

    def test_future_range_preserves_error_and_no_storage_reads(self):
        body = self.call('2026-10-07', '2026-10-08')
        self.assertEqual(self.result['statusCode'], 400)
        self.assertEqual(body['error']['code'], 'INVALID_DATE')
        self.assertEqual(body['error']['message'], 'Energy Analytics 只能查询今天或过去的时间范围。')
        self.store.query_rows.assert_not_called(); self.store.state.assert_not_called()
        self.factory.assert_not_called()

    def test_invalid_install_date_preserves_503_before_future_range_error(self):
        with patch.dict(os.environ, {'BATTERY_INSTALL_DATE': 'invalid'}):
            body = self.call('2026-10-07', '2026-10-08')
        self.assertEqual(self.result['statusCode'], 503)
        self.assertEqual(body['error']['code'], 'INSTALLATION_DATE_INVALID')
        self.factory.assert_not_called()

    def test_business_result_matches_http_payload_with_explicit_dependencies(self):
        from range_analytics import build_range_summary
        for unavailable in [False, True]:
            with self.subTest(fast_unavailable=unavailable):
                self.factory.side_effect = (AppError(503, 'TELEMETRY_NOT_CONFIGURED', 'missing Fast table')
                                           if unavailable else lambda: self.fast)
                data = self.data('2026-09-30', '2026-10-02')
                window = web.bounds(self.request_params, NOW)
                business = build_range_summary(
                    window, NOW, self.store, data_start=date(2026, 9, 30),
                    battery_start=date(2026, 10, 1), telemetry_store_factory=self.factory)
                self.assertEqual(business, data)

    def test_dst_fold_day_keeps_25_hours_and_both_real_peak_instants(self):
        with patch.dict(os.environ, {'FOXESS_DATA_START_DATE': '2026-04-01',
                                     'BATTERY_INSTALL_DATE': '2026-04-01'}):
            first = int(datetime(2026, 4, 5, 2, 30, tzinfo=ZONE, fold=0).timestamp() * 1000)
            second = int(datetime(2026, 4, 5, 2, 30, tzinfo=ZONE, fold=1).timestamp() * 1000)
            self.store.rows = [
                {'epoch_ms': first, 'timestamp_local': iso(first / 1000), 'pv_power_kw': 1},
                {'epoch_ms': second, 'timestamp_local': iso(second / 1000), 'pv_power_kw': 3}]
            data = self.data('2026-04-05', '2026-04-06', 'day')
        self.assertEqual(data['range']['end_ms'] - data['range']['start_ms'], 25 * 3600000)
        self.assertEqual(data['data_quality']['expected_samples'], 25 * 12)
        self.assertEqual(data['data_quality']['raw_samples'], 2)
        self.assertEqual(data['peaks']['pv']['time'], iso(second / 1000))
        self.factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
