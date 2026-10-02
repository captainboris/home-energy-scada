"""DynamoDB historian, collector lease and durable budget. No Scan operations."""
import os
from datetime import date, datetime, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.config import Config
from botocore.exceptions import ClientError

from common import AppError, ENERGY_COUNTERS, METRICS, ZONE, iso

RAW_METRICS = tuple(metric for metric, _unit in METRICS.values())
ENERGY_COUNTER_FIELDS = tuple(metric for metric, _unit in ENERGY_COUNTERS.values())
RAW_FIELDS = RAW_METRICS + ENERGY_COUNTER_FIELDS


def is_condition_failure(exc):
    return isinstance(exc, ClientError) and exc.response['Error']['Code'] == 'ConditionalCheckFailedException'


def decimalise(value):
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: decimalise(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decimalise(v) for v in value]
    return value


class Store:
    def __init__(self, table=None, site=None):
        self.site = site or os.environ.get('SITE_ID', 'home')
        self.table = table or boto3.resource('dynamodb', config=Config(
            connect_timeout=3, read_timeout=5, retries={'mode': 'standard', 'total_max_attempts': 4}
        )).Table(os.environ['TABLE_NAME'])

    def get(self, pk, sk):
        return self.table.get_item(Key={'pk': pk, 'sk': sk}, ConsistentRead=True).get('Item')

    def put(self, item):
        self.table.put_item(Item=decimalise(item))

    def site_key(self):
        return 'SITE#' + self.site

    def day_key(self, day):
        value = day.isoformat() if isinstance(day, date) else str(day)
        return f'{self.site_key()}#DAY#{value}'

    def state(self):
        return self.get(self.site_key(), 'STATE#collector') or {'revision': 0, 'latest': {}}

    def save_state(self, state):
        self.put({**state, 'pk': self.site_key(), 'sk': 'STATE#collector'})

    def acquire(self, owner, now, seconds=240):
        try:
            self.table.put_item(Item={'pk': self.site_key(), 'sk': 'STATE#lease',
                                      'owner': owner, 'lease_until': int(now) + seconds},
                ConditionExpression='attribute_not_exists(pk) OR lease_until < :now',
                ExpressionAttributeValues={':now': int(now)})
            return True
        except ClientError as exc:
            if is_condition_failure(exc):
                return False
            raise

    def renew(self, owner, now, seconds=240):
        self.table.update_item(Key={'pk': self.site_key(), 'sk': 'STATE#lease'},
            UpdateExpression='SET lease_until = :until', ConditionExpression='#o = :owner',
            ExpressionAttributeNames={'#o': 'owner'},
            ExpressionAttributeValues={':owner': owner, ':until': int(now) + seconds})

    def release(self, owner):
        try:
            self.table.delete_item(Key={'pk': self.site_key(), 'sk': 'STATE#lease'},
                ConditionExpression='#o = :owner', ExpressionAttributeNames={'#o': 'owner'},
                ExpressionAttributeValues={':owner': owner})
        except ClientError as exc:
            if not is_condition_failure(exc):
                raise

    def consume_call(self, now, limit):
        """Sliding 24h; count attempts BEFORE the HTTP call. Caller holds the lease.

        CAS also prevents lost updates if this method is accidentally called concurrently.
        Covers THIS collector, not unrelated programs sharing the Fox account.
        """
        pk, sk = self.site_key(), 'STATE#fox_budget'
        old = self.get(pk, sk) or {}
        calls = [int(t) for t in old.get('calls_ms', []) if int(t) > int((now - 86400) * 1000)]
        if len(calls) >= limit:
            raise AppError(429, 'FOX_BUDGET_EXHAUSTED', '本程序过去24小时的 Fox 调用预算已用完，采集将稍后恢复。')
        version = int(old.get('version', 0))
        calls.append(int(now * 1000))
        condition = '#v = :v' if old else 'attribute_not_exists(pk)'
        args = {'ExpressionAttributeNames': {'#v': 'version'},
                'ExpressionAttributeValues': {':v': version}} if old else {}
        self.table.put_item(Item={'pk': pk, 'sk': sk, 'version': version + 1, 'calls_ms': calls},
                            ConditionExpression=condition, **args)
        return len(calls)

    def recent_call_count(self, now):
        budget = self.get(self.site_key(), 'STATE#fox_budget') or {}
        return sum(int(t) > int((now - 86400) * 1000) for t in budget.get('calls_ms', []))

    def partition(self, stamp_ms):
        return self.day_key(datetime.fromtimestamp(stamp_ms / 1000, ZONE).date())

    def raw_sort_key(self, stamp_ms):
        local = datetime.fromtimestamp(stamp_ms / 1000, ZONE)
        suffix = '#FOLD1' if local.fold else ''
        return 'TIME#' + local.strftime('%H:%M:%S') + suffix

    def query_day(self, day):
        request = {'KeyConditionExpression': Key('pk').eq(self.day_key(day)) & Key('sk').begins_with('TIME#'),
                   'ConsistentRead': True, 'Limit': 500}
        rows = []
        while True:
            result = self.table.query(**request)
            rows.extend(result.get('Items', []))
            if not result.get('LastEvaluatedKey'):
                break
            request['ExclusiveStartKey'] = result['LastEvaluatedKey']
        return sorted(rows, key=lambda row: int(row['epoch_ms']))

    def query_rows(self, start_ms, end_ms):
        """Exclusive end. Query each Melbourne calendar-day partition."""
        if end_ms <= start_ms:
            return []
        cursor = datetime.fromtimestamp(start_ms / 1000, ZONE).date()
        last = datetime.fromtimestamp((end_ms - 1) / 1000, ZONE).date()
        rows = []
        while cursor <= last:
            rows.extend(self.query_day(cursor))
            cursor += timedelta(days=1)
        return sorted((row for row in rows if start_ms <= int(row['epoch_ms']) < end_ms),
                      key=lambda row: int(row['epoch_ms']))

    def get_summary(self, day):
        return self.get(self.day_key(day), 'SUMMARY#daily')

    def save_summary(self, day, summary):
        self.put({**summary, 'pk': self.day_key(day), 'sk': 'SUMMARY#daily'})

    def merge_samples(self, samples):
        """One timestamp row; merge fields so missing metrics cannot erase valid data.

        Invalid markers are stored for new samples, to preserve chart gaps. Repeated
        valid samples are skipped. A later valid correction replaces the old value.
        Collector lease serializes writers, including reconciliation/backfill.
        """
        if not samples:
            return 0, {}, set()
        existing = {int(row['epoch_ms']): row for row in self.query_rows(min(samples), max(samples) + 1)}
        changed, latest, affected_days = 0, {}, set()
        for stamp_ms, incoming in sorted(samples.items()):
            old = existing.get(stamp_ms, {})
            local = datetime.fromtimestamp(stamp_ms / 1000, ZONE)
            affected_days.add(local.date())
            values = {metric: old.get(metric) for metric in RAW_FIELDS}
            qualities = dict(old.get('quality', {}))
            for metric, point in incoming.items():
                if metric not in RAW_FIELDS:
                    continue
                previous = values.get(metric)
                if point.get('value') is None and previous is not None:
                    continue
                values[metric] = point.get('value')
                qualities[metric] = point.get('quality', 'missing')
            for metric in RAW_FIELDS:
                qualities.setdefault(metric, 'missing' if values[metric] is None else 'good')
            item = {
                'pk': self.partition(stamp_ms),
                'sk': self.raw_sort_key(stamp_ms),
                'timestamp_local': local.isoformat(timespec='seconds'),
                'timestamp_utc': iso(stamp_ms / 1000),
                'epoch_ms': stamp_ms,
                'quality': qualities,
                **values,
            }
            comparable_old = {key: old.get(key) for key in item}
            if not old or decimalise(item) != comparable_old:
                self.put(item)
                changed += 1
            for metric in RAW_METRICS:
                latest[metric] = {'t': stamp_ms, 'value': values[metric], 'quality': qualities[metric]}
        return changed, latest, affected_days

    def login_attempt(self, ip_hash, now):
        """Shared across Lambda instances. Count all attempts, not just failures."""
        for identifier, maximum in [(ip_hash, 5), ('global', 30)]:
            try:
                self.table.update_item(Key={'pk': 'AUTH#RATE', 'sk': f'{int(now // 60)}#{identifier}'},
                    UpdateExpression='SET expires_at = :expires ADD #n :one',
                    ConditionExpression='attribute_not_exists(#n) OR #n < :max',
                    ExpressionAttributeNames={'#n': 'attempts'},
                    ExpressionAttributeValues={':expires': int(now) + 120, ':one': 1, ':max': maximum})
            except ClientError as exc:
                if not is_condition_failure(exc):
                    raise
                raise AppError(429, 'LOGIN_RATE_LIMIT', '尝试次数较多，请一分钟后再试。') from None
