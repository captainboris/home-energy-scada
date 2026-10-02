"""Behavior tests with moto's DynamoDB implementation; no live AWS/Fox requests.

python -m pip install boto3 'moto[dynamodb]'
python -m unittest -v test_backend
"""
import base64
import gzip
import json
import os
import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

os.environ.update(AWS_DEFAULT_REGION='ap-southeast-2', AWS_ACCESS_KEY_ID='testing',
                  AWS_SECRET_ACCESS_KEY='testing', AWS_EC2_METADATA_DISABLED='true')
import boto3
from moto import mock_aws

import collector
import lambda_function as web
from analytics import build_daily_summary, normalise_report
from common import AppError, HISTORY_VARIABLES, ZONE, normalise_history, parse_fox_time
from storage import Store

NOW = datetime(2026, 9, 21, 0, 30, tzinfo=timezone.utc).timestamp()


def decode(result):
    raw = base64.b64decode(result['body']) if result.get('isBase64Encoded') else result['body'].encode()
    if result['headers'].get('Content-Encoding') == 'gzip':
        raw = gzip.decompress(raw)
    return json.loads(raw)


def event(path, method='GET', body=None, cookie=None, query=None):
    result = {'rawPath': path, 'requestContext': {'domainName': 'energy.test',
              'http': {'method': method, 'sourceIp': '127.0.0.1'}},
              'headers': {'content-type': 'application/json', 'origin': 'https://energy.test'},
              'body': json.dumps(body or {}), 'queryStringParameters': query or {}}
    if cookie:
        result['cookies'] = [cookie]
    return result


class EnergyTests(unittest.TestCase):
    def setUp(self):
        self.aws = mock_aws(); self.aws.start()
        self.env = patch.dict(os.environ, {'TABLE_NAME': 'energy-test', 'APP_PASSWORD': '1234567890',
            'FOX_API_KEY': 'test-key', 'FOX_DEVICE_SN': 'TEST', 'FOX_CALLS_PER_DAY': '1000'})
        self.env.start()
        self.table = boto3.resource('dynamodb').create_table(TableName='energy-test',
            AttributeDefinitions=[{'AttributeName': 'pk', 'AttributeType': 'S'}, {'AttributeName': 'sk', 'AttributeType': 'S'}],
            KeySchema=[{'AttributeName': 'pk', 'KeyType': 'HASH'}, {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
            ProvisionedThroughput={'ReadCapacityUnits': 25, 'WriteCapacityUnits': 25})
        self.store = Store(self.table, 'home')
        self.web_store = patch.object(web, 'get_store', return_value=self.store);self.web_store.start()
        self.collector_store = patch.object(collector, 'get_store', return_value=self.store);self.collector_store.start()
        self.clock = patch('time.time', return_value=NOW);self.clock.start()
        self.sleep = patch.object(collector.time, 'sleep');self.sleep.start()
        self.report = patch.object(collector, 'fetch_report', return_value={
            'energy': {'pv_kwh': 12, 'load_kwh': 10, 'grid_import_kwh': 2,
                       'grid_export_kwh': 4, 'battery_charge_kwh': 5,
                       'battery_discharge_kwh': 3},
            'hourly': {'grid_import_kwh': [0.1] * 24},
            'fetched_at': int(NOW), 'source': 'foxess_report_hourly'})
        self.report_mock=self.report.start()
        self.reserve = patch.object(collector, 'fetch_reserve_soc', return_value=40);self.reserve_mock=self.reserve.start()

    def tearDown(self):
        self.reserve.stop();self.report.stop();self.sleep.stop();self.clock.stop();self.collector_store.stop();self.web_store.stop();self.env.stop();self.aws.stop()

    def login(self):
        result = web.lambda_handler(event('/api/login', 'POST', {'password': '1234567890'}), None)
        self.assertEqual(result['statusCode'], 200)
        return result['cookies'][0].split(';')[0]

    def seed(self, stamp=None):
        stamp = stamp or int((NOW - 180) * 1000)
        self.store.merge_samples({stamp: {'pv_power_kw': {'value': 3.2, 'quality': 'good'}}})
        self.store.save_state({'revision': 2, 'last_success_at': int(NOW), 'latest': {
            'pv_power_kw': {'t': stamp, 'value': Decimal('3.2'), 'quality': 'good'}}})

    def test_auth_ten_char_password_and_tampered_cookie(self):
        cookie=self.login()
        self.assertEqual(web.lambda_handler(event('/api/history'),None)['statusCode'],401)
        self.assertEqual(web.lambda_handler(event('/api/session',cookie=cookie),None)['statusCode'],200)
        self.assertEqual(web.lambda_handler(event('/api/session',cookie=cookie[:-1]+'x'),None)['statusCode'],401)
        with patch.dict(os.environ,APP_PASSWORD='123456789'):
            self.assertEqual(web.lambda_handler(event('/api/login','POST',{'password':'123456789'}),None)['statusCode'],503)

    def test_polling_does_not_extend_idle_session(self):
        cookie=self.login()
        with patch('time.time',return_value=NOW+1799):
            self.assertEqual(web.lambda_handler(event('/api/history',cookie=cookie),None)['statusCode'],200)
        with patch('time.time',return_value=NOW+1800):
            result=web.lambda_handler(event('/api/history',cookie=cookie),None)
            self.assertEqual(result['statusCode'],401)
            self.assertEqual(decode(result)['error']['code'],'SESSION_IDLE')

    def test_activity_extends_session_logout_and_password_change_revoke(self):
        cookie=self.login()
        with patch('time.time',return_value=NOW+1000):
            self.assertEqual(web.lambda_handler(event('/api/activity','POST',{'idle_seconds':5},cookie),None)['statusCode'],200)
        with patch('time.time',return_value=NOW+2000):
            self.assertEqual(web.lambda_handler(event('/api/session',cookie=cookie),None)['statusCode'],200)
        web.lambda_handler(event('/api/logout','POST',cookie=cookie),None)
        self.assertEqual(web.lambda_handler(event('/api/activity','POST',cookie=cookie),None)['statusCode'],401)
        cookie=self.login()
        with patch.dict(os.environ,APP_PASSWORD='changed-password'):
            self.assertEqual(web.lambda_handler(event('/api/history',cookie=cookie),None)['statusCode'],401)

    def test_origin_and_persistent_login_rate_limit(self):
        cross=event('/api/login','POST',{'password':'1234567890'});cross['headers']['origin']='https://evil.example'
        self.assertEqual(web.lambda_handler(cross,None)['statusCode'],403)
        for _ in range(5):
            self.assertEqual(web.lambda_handler(event('/api/login','POST',{'password':'wrong'}),None)['statusCode'],401)
        self.assertEqual(web.lambda_handler(event('/api/login','POST',{'password':'wrong'}),None)['statusCode'],429)

    def test_today_week_month_and_dst_calendar_boundaries(self):
        for iso, hours in [('2026-10-04T05:00:00+00:00',23),('2026-04-05T05:00:00+00:00',25)]:
            result=web.bounds({},datetime.fromisoformat(iso).timestamp())
            self.assertEqual((result['end_ms']-result['start_ms'])/3600000,hours)
        today=web.bounds({},NOW)
        self.assertEqual(today['start_date'],'2026-09-21')
        self.assertEqual(datetime.fromtimestamp(today['start_ms']/1000,timezone.utc).hour,14)
        self.assertEqual(web.bounds({'range':'week'},NOW)['end_date'],'2026-09-27')
        self.assertEqual(web.bounds({'range':'month'},NOW)['end_date'],'2026-09-30')
        self.assertEqual(web.bounds({'range':'custom','start':'2026-01-01','end':'2026-12-31'},NOW)['end_date'],'2026-12-31')
        with self.assertRaises(AppError):web.bounds({'range':'custom','start':'2025-01-01','end':'2026-12-31'},NOW)

    def test_exact_history_range_supports_time_quarter_and_year(self):
        begin=int(datetime(2026,9,22,18,0,tzinfo=ZONE).timestamp()*1000)
        finish=int(datetime(2026,9,23,9,0,tzinfo=ZONE).timestamp()*1000)
        exact=web.bounds({'range':'other','from_ms':str(begin),'to_ms':str(finish)},NOW)
        self.assertEqual(exact['start_ms'],begin);self.assertEqual(exact['end_ms'],finish)
        self.assertTrue(exact['start_at'].startswith('2026-09-22T18:00:00'))
        quarter_start=int(datetime(2026,7,1,tzinfo=ZONE).timestamp()*1000)
        quarter_end=int(datetime(2026,10,1,tzinfo=ZONE).timestamp()*1000)
        self.assertEqual(web.bounds({'range':'quarter','from_ms':str(quarter_start),'to_ms':str(quarter_end)},NOW)['end_date'],'2026-09-30')
        year_start=int(datetime(2028,1,1,tzinfo=ZONE).timestamp()*1000)
        year_end=int(datetime(2029,1,1,tzinfo=ZONE).timestamp()*1000)
        self.assertEqual(web.bounds({'range':'year','from_ms':str(year_start),'to_ms':str(year_end)},NOW)['end_date'],'2028-12-31')
        with self.assertRaises(AppError):web.bounds({'from_ms':'bad','to_ms':str(finish)},NOW)

    def test_manual_refresh_reads_db_and_never_fox(self):
        cookie=self.login();self.seed()
        with patch.object(collector,'fetch_fox',side_effect=AssertionError('web must not call Fox')):
            first=decode(web.lambda_handler(event('/api/history',cookie=cookie),None))['data']
            q={'known_revision':str(first['revision']),'known_range':first['range']['key']}
            with patch.object(self.store,'query_rows',wraps=self.store.query_rows) as query:
                cached=decode(web.lambda_handler(event('/api/history',cookie=cookie,query=q),None))['data']
                self.assertTrue(cached['not_modified']);self.assertEqual(query.call_count,0)
                forced=decode(web.lambda_handler(event('/api/history',cookie=cookie,query={**q,'force':'1'}),None))['data']
                self.assertFalse(forced['not_modified']);self.assertEqual(query.call_count,1)
                self.assertEqual(forced['series'][0]['points'][0][1],3.2)

    def test_db_upsert_duplicate_correction_and_invalid_preservation(self):
        stamp=int(NOW*1000)
        point={stamp:{'pv_power_kw':{'value':2,'quality':'good'},'battery_soc_pct':{'value':50,'quality':'good'}}}
        self.assertEqual(self.store.merge_samples(point)[0],1)
        self.assertEqual(self.store.merge_samples(point)[0],0)
        self.store.merge_samples({stamp:{'pv_power_kw':{'value':3,'quality':'good'}}})
        self.store.merge_samples({stamp:{'pv_power_kw':{'value':None,'quality':'invalid'}}})
        row=self.store.query_rows(stamp,stamp+1)[0]
        self.assertEqual(row['pv_power_kw'],3);self.assertEqual(row['battery_soc_pct'],50)
        self.store.merge_samples({stamp+1000:{'pv_power_kw':{'value':None,'quality':'invalid'}}})
        self.assertIsNone(self.store.query_rows(stamp+1000,stamp+1001)[0]['pv_power_kw'])

    def test_query_pages_days_and_exclusive_end(self):
        start=int(datetime(2026,8,31,23,55,tzinfo=ZONE).timestamp()*1000)
        with self.table.batch_writer() as writer:
            for i in range(610):
                stamp=start+i*1000
                local=datetime.fromtimestamp(stamp/1000,ZONE)
                writer.put_item(Item={'pk':self.store.partition(stamp),'sk':self.store.raw_sort_key(stamp),
                    'timestamp_local':local.isoformat(timespec='seconds'),'timestamp_utc':datetime.fromtimestamp(stamp/1000,timezone.utc).isoformat(),
                    'epoch_ms':stamp})
        rows=self.store.query_rows(start,start+609000)
        self.assertEqual(len(rows),609)
        self.assertEqual(int(rows[-1]['epoch_ms']),start+608000)

    def test_lease_and_sliding_budget_survive_new_instances(self):
        self.assertTrue(self.store.acquire('one',NOW))
        self.assertFalse(Store(self.table,'home').acquire('two',NOW))
        self.store.release('two');self.assertFalse(self.store.acquire('two',NOW))
        self.store.release('one');self.assertTrue(self.store.acquire('two',NOW))
        self.store.consume_call(NOW,2);Store(self.table,'home').consume_call(NOW+1,2)
        with self.assertRaises(AppError):self.store.consume_call(NOW+2,2)
        self.assertEqual(self.store.consume_call(NOW+86401,2),1)

    def test_window_overlap_and_empty_days_make_catchup_progress(self):
        through=NOW-3*86400
        self.store.save_state({'through':int(through),'catchup':True,'revision':0,'latest':{}})
        with patch.object(collector,'fetch_fox',return_value=([],[])) as fetch,patch('time.sleep'):
            result=collector.lambda_handler({'action':'poll'},None)
            self.assertTrue(result['ok'])
            first=fetch.call_args_list[0].args
            self.assertEqual(first[0],int(through)-900);self.assertEqual(first[1]-first[0],86400)
            self.assertGreater(int(self.store.state()['through']),through)

    def test_normal_window_anchors_at_latest_sample(self):
        self.seed()
        self.store.save_state({**self.store.state(),'through':int(NOW-60),'reconciled_day':'2026-09-20'})
        with patch.object(collector,'fetch_fox',return_value=([],[])) as fetch:
            self.assertTrue(collector.lambda_handler({'action':'poll'},None)['ok'])
            self.assertEqual(fetch.call_args.args[0],int(NOW-180)-900)

    def test_failed_write_does_not_advance_cursor_and_failure_consumes_budget(self):
        self.store.save_state({'through':int(NOW-3600),'revision':0,'latest':{}})
        series=[{'metric':'pv_power_kw','points':[{'timestamp':'2026-09-21T00:27:00Z','value':2,'quality':'good'}]}]
        with patch.object(collector,'fetch_fox',return_value=(series,[])),patch.object(self.store,'merge_samples',side_effect=RuntimeError('interrupted')):
            result=collector.lambda_handler({'action':'poll'},None)
        self.assertFalse(result['ok']);self.assertEqual(int(self.store.state()['through']),int(NOW-3600))
        self.assertEqual(self.store.recent_call_count(NOW),1)
        with patch.object(collector,'fetch_fox') as fetch:
            self.assertEqual(collector.lambda_handler({'action':'poll'},None)['skipped'],'backoff');fetch.assert_not_called()

    def test_nightly_reconciliation_does_not_regress_latest(self):
        self.seed()
        older=[{'metric':'pv_power_kw','points':[{'timestamp':'2026-09-20T00:27:00Z','value':9,'quality':'good'}]}]
        with patch.object(collector,'fetch_fox',side_effect=[([],[]),(older,[])]),patch('time.sleep'):
            result=collector.lambda_handler({'action':'poll'},None)
        self.assertTrue(result['ok']);self.assertEqual(result['windows'],2)
        state=self.store.state();self.assertEqual(state['reconciled_day'],'2026-09-20')
        self.assertEqual(state['latest']['pv_power_kw']['value'],Decimal('3.2'))

    def test_backfill_progress_and_dst_day_split(self):
        self.store.save_state({'revision':0,'latest':{},'reconciled_day':'2026-09-20'})
        with patch.object(collector,'fetch_fox',return_value=([],[])),patch('time.sleep'):
            result=collector.lambda_handler({'action':'backfill','start_date':'2026-09-01','end_date':'2026-09-03'},None)
        self.assertTrue(result['ok']);state=self.store.state()
        self.assertLess(state['backfill_next'],state['backfill_end'])
        self.assertIsNotNone(self.store.get_summary('2026-09-01'))
        spring=datetime(2026,4,6,0,0,tzinfo=timezone.utc).timestamp()
        self.store.save_state({'revision':0,'latest':{}})
        with patch('time.time',return_value=spring),patch.object(collector,'fetch_fox',return_value=([],[])) as fetch,patch('time.sleep'):
            collector.lambda_handler({'action':'poll'},None)
            state=self.store.state();self.assertEqual(int(state['reconcile_end'])-int(state['reconcile_next']),3600)
            collector.lambda_handler({'action':'poll'},None)
            self.assertEqual(self.store.state()['reconciled_day'],'2026-04-05')
            self.assertTrue(all(end-start<=86400 for start,end in [call.args for call in fetch.call_args_list]))

    def test_fox_offset_units_invalid_and_duplicate(self):
        stamp='2026-09-21 10:27:00 AEST+1000'
        payload={'errno':0,'result':[{'deviceSN':'TEST','datas':[{'variable':'pvPower','unit':'W','data':[
            {'time':stamp,'value':1234},{'time':stamp,'value':None}]}]}]}
        series,_=normalise_history(payload,'TEST',NOW-600,NOW)
        self.assertEqual(series[0]['points'][0]['value'],1.234)
        self.assertEqual(parse_fox_time(stamp),NOW-180)

    def test_human_readable_daily_schema_and_state_keys(self):
        stamp=int(datetime(2026,9,22,17,35,tzinfo=ZONE).timestamp()*1000)
        self.store.merge_samples({stamp:{'pv_power_kw':{'value':4.2,'quality':'good'}}})
        row=self.store.query_rows(stamp,stamp+1)[0]
        self.assertEqual(row['pk'],'SITE#home#DAY#2026-09-22')
        self.assertEqual(row['sk'],'TIME#17:35:00')
        self.assertEqual(row['timestamp_local'][:19],'2026-09-22T17:35:00')
        self.assertTrue(row['timestamp_utc'].endswith('Z'))
        self.assertEqual(int(row['epoch_ms']),stamp)
        self.assertEqual(row['pv_power_kw'],Decimal('4.2'))
        self.assertIn('battery_soc_pct',row)
        self.store.save_state({'revision':7,'latest':{}})
        self.assertEqual(self.store.get('SITE#home','STATE#collector')['revision'],7)
        self.store.save_summary(date(2026,9,22),{'date':'2026-09-22'})
        self.assertEqual(self.store.get('SITE#home#DAY#2026-09-22','SUMMARY#daily')['date'],'2026-09-22')

    def test_dst_fold_sort_keys_remain_human_readable_and_unique(self):
        first=int(datetime(2026,4,5,2,30,tzinfo=ZONE,fold=0).timestamp()*1000)
        second=int(datetime(2026,4,5,2,30,tzinfo=ZONE,fold=1).timestamp()*1000)
        self.assertNotEqual(first,second)
        self.assertEqual(self.store.raw_sort_key(first),'TIME#02:30:00')
        self.assertEqual(self.store.raw_sort_key(second),'TIME#02:30:00#FOLD1')

    def test_history_request_collects_counters_without_an_extra_api_call(self):
        with patch.object(collector,'fox_request',return_value={'errno':0,'result':[]}) as request:
            collector.fetch_fox(NOW-300,NOW)
        variables=request.call_args.args[1]['variables']
        self.assertEqual(set(variables),set(HISTORY_VARIABLES))
        self.assertIn('gridConsumption',variables)
        self.assertIn('gridConsumptionPower',variables)

    def test_report_energy_mapping_and_daily_analytics_sources(self):
        variables={
            'PVEnergyTotal':1.0,'loads':2.0,'gridConsumption':0.5,'feedin':0.25,
            'chargeEnergyToTal':0.4,'dischargeEnergyToTal':0.3}
        payload={'errno':0,'result':[{'variable':name,'unit':'kWh','values':[value]*24}
                                     for name,value in variables.items()]}
        report=normalise_report(payload,NOW)
        self.assertEqual(report['energy']['pv_kwh'],24)
        self.assertEqual(report['energy']['load_kwh'],48)
        self.assertEqual(sum(report['hourly']['grid_import_kwh'][18:21]),1.5)
        day=date(2026,9,21);base=int(datetime.combine(day,datetime.min.time(),ZONE).timestamp()*1000)
        points={
            base+5*3600000:{'pv_power_kw':{'value':1,'quality':'good'},'battery_soc_pct':{'value':50,'quality':'good'}},
            base+5*3600000+300000:{'pv_power_kw':{'value':6,'quality':'good'},'battery_soc_pct':{'value':40,'quality':'good'}},
            base+18*3600000:{'grid_import_power_kw':{'value':2,'quality':'good'}},
            base+18*3600000+300000:{'grid_import_power_kw':{'value':4,'quality':'good'}},
        }
        self.store.merge_samples(points)
        summary=build_daily_summary(day,self.store.query_day(day),NOW,report=report,
                                    reserve_soc_pct=40,reserve_source='foxess_min_soc_on_grid')
        self.assertEqual(summary['energy']['pv_kwh'],24)
        self.assertEqual(summary['metric_sources']['energy']['pv_kwh'],'foxess_report_hourly')
        self.assertEqual(summary['peak_period']['grid_import_18_21_kwh'],1.5)
        self.assertEqual(summary['peaks']['pv']['kw'],6)
        self.assertTrue(summary['battery']['reserve_reached_time'].startswith('2026-09-21T05:05:00'))
        self.assertEqual(summary['performance']['self_sufficiency_pct'],75.0)

    def test_energy_falls_back_to_power_integration_without_report_metric(self):
        day=date(2026,9,21);base=int(datetime.combine(day,datetime.min.time(),ZONE).timestamp()*1000)
        self.store.merge_samples({
            base:{'load_power_kw':{'value':3,'quality':'good'}},
            base+300000:{'load_power_kw':{'value':3,'quality':'good'}},
        })
        summary=build_daily_summary(day,self.store.query_day(day),NOW,reserve_soc_pct=40)
        self.assertAlmostEqual(summary['energy']['load_kwh'],0.25)
        self.assertEqual(summary['metric_sources']['energy']['load_kwh'],'raw_power_integration')

    def test_peak_period_uses_cumulative_counter_before_power_integration(self):
        day=date(2026,9,21);base=int(datetime.combine(day,datetime.min.time(),ZONE).timestamp()*1000)
        self.store.merge_samples({
            base+17*3600000+55*60000:{'grid_import_energy_total_kwh':{'value':1.0,'quality':'good'}},
            base+18*3600000+5*60000:{'grid_import_energy_total_kwh':{'value':1.2,'quality':'good'}},
            base+20*3600000+55*60000:{'grid_import_energy_total_kwh':{'value':2.7,'quality':'good'}},
            base+21*3600000+5*60000:{'grid_import_energy_total_kwh':{'value':2.9,'quality':'good'}},
        })
        after_day=datetime(2026,9,22,1,tzinfo=timezone.utc).timestamp()
        summary=build_daily_summary(day,self.store.query_day(day),after_day,reserve_soc_pct=40)
        self.assertAlmostEqual(summary['peak_period']['grid_import_18_21_kwh'],1.7)
        self.assertEqual(summary['metric_sources']['grid_import_18_21_kwh'],'foxess_cumulative_counter')

    def test_daily_summary_api_reads_cached_item(self):
        cookie=self.login()
        item=build_daily_summary(date(2026,9,21),[],NOW,report=self.report_mock.return_value,
                                 reserve_soc_pct=40,reserve_source='foxess_min_soc_on_grid')
        item['warnings']=[];self.store.save_summary('2026-09-21',item)
        result=web.lambda_handler(event('/api/summary/daily',cookie=cookie,query={'date':'2026-09-21'}),None)
        self.assertEqual(result['statusCode'],200)
        data=decode(result)['data']
        self.assertEqual(data['date'],'2026-09-21')
        self.assertEqual(data['energy']['pv_kwh'],12)
        self.assertNotIn('_report',data)
        invalid=web.lambda_handler(event('/api/summary/daily',cookie=cookie,query={'date':'2026-09-22'}),None)
        self.assertEqual(invalid['statusCode'],400)

    def test_range_analytics_sums_only_official_reports_and_reads_minimum_soc(self):
        cookie=self.login()
        for selected in [date(2026,9,20),date(2026,9,21)]:
            item=build_daily_summary(selected,[],NOW,report=self.report_mock.return_value,
                                     reserve_soc_pct=40,reserve_source='foxess_min_soc_on_grid')
            self.store.save_summary(selected,item)
        low_at=int(datetime(2026,9,20,6,42,tzinfo=ZONE).timestamp()*1000)
        self.store.merge_samples({
            low_at-300000:{'battery_soc_pct':{'value':31,'quality':'good'},
                            'pv_power_kw':{'value':1,'quality':'good'}},
            low_at:{'battery_soc_pct':{'value':18,'quality':'good'},
                    'pv_power_kw':{'value':4.5,'quality':'good'}},
        })
        begin=int(datetime(2026,9,20,tzinfo=ZONE).timestamp()*1000)
        finish=int(NOW*1000)+1
        result=web.lambda_handler(event('/api/summary/range',cookie=cookie,query={
            'range':'week','from_ms':str(begin),'to_ms':str(finish)}),None)
        self.assertEqual(result['statusCode'],200)
        data=decode(result)['data']
        self.assertEqual(data['energy']['pv_kwh'],24)
        self.assertEqual(data['metric_sources']['energy']['pv_kwh'],'foxess_report_daily_sum')
        self.assertEqual(data['battery']['minimum_soc_pct'],18)
        self.assertTrue(data['battery']['minimum_soc_time'].startswith('2026-09-20T06:42:00'))
        self.assertEqual(data['peaks']['pv']['kw'],4.5)
        self.assertEqual(data['report_dates']['expected_days'],2)

    def test_fast_month_home_load_peak_uses_rollup_max_timestamp(self):
        fast_now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc).timestamp()
        start = int(datetime(2026, 10, 1, tzinfo=ZONE).timestamp() * 1000)
        end = int(datetime(2026, 11, 1, tzinfo=ZONE).timestamp() * 1000)
        bucket = start + 18 * 3600 * 1000
        peak_stamp = bucket + 42 * 1000

        class Telemetry:
            def query(self, lower, upper, raw):
                if raw or not lower <= bucket < upper:
                    return []
                stat = {'count': 12, 'min': 1, 'max': 8.42, 'avg': 2.1,
                        'last': 2, 'min_ts': bucket + 5000,
                        'max_ts': peak_stamp, 'last_ts': bucket + 55000}
                return [{'bucket_start_ms': bucket, 'sample_count': 12,
                         'source_first_ms': bucket + 5000,
                         'source_last_ms': bucket + 55000,
                         'metrics': {metric: dict(stat) for metric in (
                             'pv_power_kw', 'load_power_kw',
                             'grid_import_power_kw', 'grid_export_power_kw')}}]

            def health(self):
                return {'healthy': True, 'last_source_epoch_ms': peak_stamp}

        with patch('time.time', return_value=fast_now), \
                patch.object(web, 'get_telemetry_store', return_value=Telemetry()), \
                patch.dict(os.environ, {'FOXESS_DATA_START_DATE': '2026-10-01'}):
            cookie = self.login()
            result = web.lambda_handler(event('/api/summary/range', cookie=cookie, query={
                'range': 'month', 'from_ms': str(start), 'to_ms': str(end)}), None)
        self.assertEqual(result['statusCode'], 200)
        data = decode(result)['data']
        self.assertEqual(data['peaks']['load']['kw'], 8.42)
        self.assertEqual(data['peaks']['load']['source'],
                         'fast_telemetry_rollup_max')
        self.assertEqual(data['peaks']['load']['sample_resolution_seconds'], 60)
        self.assertEqual(data['metric_sources']['peak_sources']['load'],
                         'fast_telemetry_rollup_max')

    def test_current_day_partial_report_is_not_a_warning_or_power_integration(self):
        cookie=self.login()
        official=build_daily_summary(date(2026,9,20),[],NOW,report=self.report_mock.return_value,
                                     reserve_soc_pct=40)
        self.store.save_summary('2026-09-20',official)
        day=date(2026,9,21);base=int(datetime.combine(day,datetime.min.time(),ZONE).timestamp()*1000)
        self.store.merge_samples({
            base:{'load_power_kw':{'value':3,'quality':'good'}},
            base+300000:{'load_power_kw':{'value':3,'quality':'good'}},
        })
        fallback=build_daily_summary(day,self.store.query_day(day),NOW,reserve_soc_pct=40)
        self.assertEqual(fallback['metric_sources']['energy']['load_kwh'],'raw_power_integration')
        self.store.save_summary(day,fallback)
        begin=int(datetime(2026,9,20,tzinfo=ZONE).timestamp()*1000)
        result=web.lambda_handler(event('/api/summary/range',cookie=cookie,query={
            'range':'week','from_ms':str(begin),'to_ms':str(int(NOW*1000)+1)}),None)
        data=decode(result)['data']
        self.assertEqual(data['energy']['load_kwh'],10)
        self.assertEqual(data['metric_sources']['energy']['load_kwh'],
                         'foxess_report_daily_sum')
        self.assertEqual(data['warnings'],[])

    def test_completed_date_missing_official_report_still_warns(self):
        cookie=self.login()
        official=build_daily_summary(date(2026,9,19),[],NOW,report=self.report_mock.return_value,
                                     reserve_soc_pct=40)
        self.store.save_summary('2026-09-19',official)
        day=date(2026,9,20);base=int(datetime.combine(day,datetime.min.time(),ZONE).timestamp()*1000)
        self.store.merge_samples({
            base:{'load_power_kw':{'value':3,'quality':'good'}},
            base+300000:{'load_power_kw':{'value':3,'quality':'good'}},
        })
        fallback=build_daily_summary(day,self.store.query_day(day),NOW,reserve_soc_pct=40)
        self.store.save_summary(day,fallback)
        begin=int(datetime(2026,9,19,tzinfo=ZONE).timestamp()*1000)
        finish=int(datetime(2026,9,21,tzinfo=ZONE).timestamp()*1000)
        result=web.lambda_handler(event('/api/summary/range',cookie=cookie,query={
            'range':'other','from_ms':str(begin),'to_ms':str(finish)}),None)
        data=decode(result)['data']
        self.assertIsNone(data['energy']['load_kwh'])
        self.assertEqual(data['metric_sources']['energy']['load_kwh'],
                         'unavailable_missing_official_report')
        self.assertIn('OFFICIAL_REPORT_MISSING',
                      [item['code'] for item in data['warning_codes']])

    def test_installation_dates_exclude_false_missing_and_battery_metrics(self):
        cookie=self.login()
        with patch.dict(os.environ, {'FOXESS_DATA_START_DATE':'2026-09-10',
                                     'BATTERY_INSTALL_DATE':'2026-09-15'}):
            before=int(datetime(2026,9,1,tzinfo=ZONE).timestamp()*1000)
            before_end=int(datetime(2026,9,6,tzinfo=ZONE).timestamp()*1000)
            result=web.lambda_handler(event('/api/summary/range',cookie=cookie,query={
                'range':'other','from_ms':str(before),'to_ms':str(before_end)}),None)
            data=decode(result)['data']
            self.assertEqual(data['warnings'],[])
            self.assertEqual(data['report_dates']['expected_days'],0)
            self.assertEqual(data['data_quality']['expected_samples'],0)
            self.assertIsNone(data['data_quality']['raw_coverage_pct'])
            self.assertFalse(data['availability']['battery_applicable'])
            self.assertIsNone(data['energy']['battery_charge_kwh'])
            self.assertEqual(data['metric_sources']['energy']['battery_charge_kwh'],
                             'not_applicable_before_battery_install')

            for selected in [date(2026,9,10)+timedelta(days=offset) for offset in range(5)]:
                item=build_daily_summary(selected,[],NOW,report=self.report_mock.return_value,
                                         reserve_soc_pct=40)
                self.store.save_summary(selected,item)
            start=int(datetime(2026,9,10,tzinfo=ZONE).timestamp()*1000)
            end=int(datetime(2026,9,15,tzinfo=ZONE).timestamp()*1000)
            result=web.lambda_handler(event('/api/summary/range',cookie=cookie,query={
                'range':'other','from_ms':str(start),'to_ms':str(end)}),None)
            data=decode(result)['data']
            self.assertEqual(data['warnings'],[])
            self.assertFalse(data['battery']['applicable'])
            self.assertEqual(data['energy']['pv_kwh'],60)
            self.assertIsNone(data['energy']['battery_discharge_kwh'])

    def test_today_without_report_has_no_missing_warning(self):
        cookie=self.login()
        start=int(datetime(2026,9,21,tzinfo=ZONE).timestamp()*1000)
        end=int(datetime(2026,9,22,tzinfo=ZONE).timestamp()*1000)
        result=web.lambda_handler(event('/api/summary/range',cookie=cookie,query={
            'range':'day','from_ms':str(start),'to_ms':str(end)}),None)
        data=decode(result)['data']
        self.assertEqual(data['warnings'],[])
        self.assertEqual(data['warning_codes'],[])
        self.assertEqual(data['report_dates']['completed_expected_days'],0)

    def test_structured_auth_logging_and_safe_request_id(self):
        context=SimpleNamespace(aws_request_id='req-auth-401')
        with patch('builtins.print') as output:
            result=web.lambda_handler(event('/api/history'),context)
        body=decode(result)
        self.assertEqual(result['statusCode'],401)
        self.assertEqual(body['error']['code'],'SESSION_TOKEN_MISSING')
        self.assertEqual(body['error']['request_id'],'req-auth-401')
        self.assertEqual(result['headers']['X-Request-ID'],'req-auth-401')
        log=json.loads(output.call_args.args[0])
        self.assertEqual(log['internal_error_code'],'SESSION_TOKEN_MISSING')
        self.assertEqual(log['auth_stage'],'session_cookie')
        self.assertFalse(log['session_token_present'])
        self.assertIn('duration_ms',log)

    def test_unexpected_logging_redacts_secrets_and_keeps_stack_trace(self):
        context=SimpleNamespace(aws_request_id='req-500')
        with patch.object(web,'dispatch',side_effect=RuntimeError('boom 1234567890')), \
                patch('builtins.print') as output:
            result=web.lambda_handler(event('/api/history'),context)
        self.assertEqual(result['statusCode'],503)
        log=json.loads(output.call_args.args[0])
        self.assertEqual(log['internal_error_code'],'WEB_FAILED')
        self.assertEqual(log['exception_type'],'RuntimeError')
        self.assertIn('[REDACTED]',log['exception_message'])
        self.assertNotIn('1234567890',json.dumps(log))
        self.assertIn('stack_trace',log)

    def test_collector_recomputes_summary_and_throttles_today_report(self):
        self.seed();state=self.store.state();state.update(reconciled_day='2026-09-20',
            reserve_checked_day='2026-09-21',reserve_soc_pct=40,reserve_source='foxess_min_soc_on_grid')
        self.store.save_state(state);self.report_mock.reset_mock()
        with patch.object(collector,'fetch_fox',return_value=([],[])):
            first=collector.lambda_handler({'action':'poll'},None)
            with patch('time.time',return_value=NOW+300):
                second=collector.lambda_handler({'action':'poll'},None)
        self.assertTrue(first['ok'] and second['ok'])
        self.assertEqual(self.report_mock.call_count,1)
        self.assertIsNotNone(self.store.get_summary('2026-09-21'))

    def test_report_failure_is_nonfatal_and_summary_remains_recomputable(self):
        self.seed();state=self.store.state();state.update(reconciled_day='2026-09-20',
            reserve_checked_day='2026-09-21',reserve_soc_pct=40,reserve_source='foxess_min_soc_on_grid')
        self.store.save_state(state);self.report_mock.side_effect=AppError(502,'FOX_REPORT_ERROR','temporary')
        with patch.object(collector,'fetch_fox',return_value=([],[])):
            result=collector.lambda_handler({'action':'poll'},None)
            with patch('time.time',return_value=NOW+300):
                again=collector.lambda_handler({'action':'poll'},None)
        self.assertTrue(result['ok'])
        self.assertTrue(again['ok']);self.assertEqual(self.report_mock.call_count,1)
        self.assertIn('report_warning',self.store.state())
        summary=self.store.get_summary('2026-09-21')
        self.assertEqual(summary['metric_sources']['energy']['pv_kwh'],'raw_power_integration')

    def test_daily_static_assets_are_served(self):
        page=web.lambda_handler(event('/daily'),None)
        script=web.lambda_handler(event('/daily.js'),None)
        shared=web.lambda_handler(event('/shared.js'),None)
        self.assertEqual(page['statusCode'],200)
        self.assertIn('HOME ENERGY / 05 · ENERGY ANALYTICS',page['body'])
        self.assertEqual(script['headers']['Content-Type'],'application/javascript; charset=utf-8')
        self.assertEqual(shared['headers']['Content-Type'],'application/javascript; charset=utf-8')

    def test_fast_telemetry_api_is_authenticated_and_independent(self):
        stamp=int((NOW-60)*1000)
        row={'source_epoch_ms':stamp,'pv_power_kw':2.5,'load_power_kw':1.2,
             'grid_import_power_kw':0.0,'grid_export_power_kw':1.3,
             'battery_charge_power_kw':0.0,'battery_discharge_power_kw':0.0,
             'battery_soc_pct':82}
        class Telemetry:
            def query(self,start,end,raw):
                return [row] if raw and start <= stamp < end else []
            def health(self):
                return {'healthy':True,'connected':True,'state':'LIVE',
                        'first_source_epoch_ms':stamp,'last_source_epoch_ms':stamp,
                        'collector_version':'0.5.0'}
        unauth=web.lambda_handler(event('/api/telemetry/history'),None)
        self.assertEqual(unauth['statusCode'],401)
        cookie=self.login()
        with patch.object(web,'get_telemetry_store',return_value=Telemetry()):
            result=web.lambda_handler(event('/api/telemetry/history',cookie=cookie),None)
            health=web.lambda_handler(event('/api/telemetry/health',cookie=cookie),None)
        data=decode(result)['data']
        self.assertEqual(result['statusCode'],200)
        self.assertTrue(data['available'])
        self.assertEqual(data['source'],'foxess_ws')
        self.assertEqual(data['resolution'],'5s_raw')
        self.assertTrue(decode(health)['data']['health']['healthy'])

    def test_compressed_large_response(self):
        payload={'large':['abc123']*10000}
        result=web.response(200,payload)
        self.assertTrue(result['isBase64Encoded']);self.assertEqual(decode(result),payload)

    def test_bad_backfill_input_does_not_pause_normal_collection(self):
        self.seed();before=self.store.state()
        result=collector.lambda_handler({'action':'backfill','start_date':'bad','end_date':'2026-09-21'},None)
        self.assertEqual(result['error'],'INVALID_BACKFILL')
        self.assertEqual(self.store.state(),before)
        self.assertEqual(self.store.recent_call_count(NOW),0)


if __name__ == '__main__':
    unittest.main()
