"""Private, scheduled FoxESS collector. Invoke with {"action":"poll"}.

Normal polling, crash recovery, daily reconciliation and optional backfill keep
the v0.2 lifecycle: one DynamoDB lease, a sliding 24h API budget and one
idempotent raw writer. Daily summaries are overwriteable derived records.
"""
import json
import os
import secrets
import time
from datetime import date, datetime, time as daytime, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from analytics import (REPORT_VARIABLES, build_daily_summary, local_days_for_window,
                       normalise_report, normalise_reserve_soc)
from common import (AppError, HISTORY_VARIABLES, ZONE, fox_signature,
                    normalise_history, parse_fox_time)
from storage import Store

FOX_HOST = 'https://www.foxesscloud.com'
HISTORY_PATH = '/op/v0/device/history/query'
REPORT_PATH = '/op/v0/device/report/query'
RESERVE_PATH = '/op/v0/device/battery/soc/get'
MAX_FOX_BYTES = 5 * 1024 * 1024
OVERLAP = 15 * 60
REPORT_REFRESH_SECONDS = 15 * 60


def get_store():
    return Store()


def fox_request(path, body=None, query=None):
    token = os.environ.get('FOX_API_KEY', '').strip()
    if not token:
        raise AppError(503, 'FOX_NOT_CONFIGURED', '请在采集 Lambda 设置 FOX_API_KEY。')
    timestamp = str(int(time.time() * 1000))
    headers = {'Content-Type': 'application/json', 'token': token, 'timestamp': timestamp,
               'signature': fox_signature(path, token, timestamp), 'lang': 'en',
               'User-Agent': 'HomeEnergyHistorian/0.4 (personal-read-only-collector)'}
    url = FOX_HOST + path + (('?' + urlencode(query)) if query else '')
    raw_body = json.dumps(body).encode() if body is not None else None
    try:
        with urlopen(Request(url, data=raw_body, headers=headers,
                             method='POST' if body is not None else 'GET'), timeout=12) as source:
            raw = source.read(MAX_FOX_BYTES + 1)
        if len(raw) > MAX_FOX_BYTES:
            raise AppError(502, 'FOX_RESPONSE_TOO_LARGE', 'Fox 响应超过大小限制。')
        payload = json.loads(raw)
    except HTTPError as exc:
        raise AppError(502, 'FOX_RATE_LIMIT' if exc.code == 429 else 'FOX_HTTP_ERROR',
                       f'Fox HTTP 错误 {exc.code}。') from None
    except (URLError, TimeoutError, OSError):
        raise AppError(502, 'FOX_UNREACHABLE', '暂时无法连接 Fox，后台会稍后重试。') from None
    except (ValueError, UnicodeDecodeError):
        raise AppError(502, 'FOX_RESPONSE_FORMAT', 'Fox 未返回有效 JSON。') from None
    if isinstance(payload, dict) and str(payload.get('errno')) == '40400':
        raise AppError(429, 'FOX_RATE_LIMIT', 'Fox 正在限流，采集将暂停后恢复。')
    return payload


def fetch_fox(start, end):
    sn = os.environ.get('FOX_DEVICE_SN', '').strip()
    if not sn:
        raise AppError(503, 'FOX_NOT_CONFIGURED', '请在采集 Lambda 设置 FOX_DEVICE_SN。')
    if not 0 < end - start <= 86400:
        raise AppError(400, 'INVALID_FOX_WINDOW', '每次 Fox 查询必须在24小时以内。')
    payload = fox_request(HISTORY_PATH, {'sn': sn, 'variables': list(HISTORY_VARIABLES),
                                         'begin': int(start * 1000), 'end': int(end * 1000)})
    return normalise_history(payload, sn, start, end, os.environ.get('FOX_NAIVE_TIMEZONE', 'UTC'))


def fetch_report(day):
    sn = os.environ.get('FOX_DEVICE_SN', '').strip()
    body = {'sn': sn, 'year': day.year, 'month': day.month, 'day': day.day,
            'dimension': 'day', 'variables': list(REPORT_VARIABLES)}
    return normalise_report(fox_request(REPORT_PATH, body), time.time())


def fetch_reserve_soc():
    sn = os.environ.get('FOX_DEVICE_SN', '').strip()
    return normalise_reserve_soc(fox_request(RESERVE_PATH, query={'sn': sn}))


def day_start(day):
    return int(datetime.combine(day, daytime.min, ZONE).timestamp())


def validate_backfill(event, now):
    try:
        start = date.fromisoformat(event['start_date'])
        end = date.fromisoformat(event['end_date'])
        if not 0 <= (end - start).days < 31 or end > datetime.fromtimestamp(now, ZONE).date():
            raise ValueError()
        return day_start(start), min(int(now), day_start(end + timedelta(days=1)))
    except (KeyError, TypeError, ValueError):
        raise AppError(400, 'INVALID_BACKFILL',
                       'start_date / end_date 使用 YYYY-MM-DD，含结束日，最多31天且不能晚于今天。') from None


def plan_window(through, now):
    start = int(through) - OVERLAP if through is not None else int(now) - 86400
    return start, min(int(now), start + 86400)


def guarded_fox_call(store, state, owner, callback):
    """Count and persist every upstream attempt before making it."""
    now = time.time()
    store.renew(owner, now)
    wait = float(state.get('last_request_at', 0)) + 1.1 - now
    if wait > 0:
        time.sleep(min(wait, 1.1))
    limit = max(1, min(1400, int(os.environ.get('FOX_CALLS_PER_DAY', '1000'))))
    count = store.consume_call(time.time(), limit)
    state['last_request_at'] = time.time()
    state['calls_last_24h'] = count
    store.save_state(state)
    return callback()


def ingest_window(store, state, owner, start, end, context):
    if end <= start:
        return 0, set()
    if context and context.get_remaining_time_in_millis() < 30000:
        raise AppError(503, 'TIME_BUDGET', '本次执行时间不足，下一次定时采集将继续。')
    series, warnings = guarded_fox_call(store, state, owner, lambda: fetch_fox(start, end))
    samples = {}
    for row in series:
        for point in row['points']:
            stamp = round(parse_fox_time(point['timestamp']) * 1000)
            samples.setdefault(stamp, {})[row['metric']] = {
                'value': point['value'], 'quality': point['quality']}
    state['revision'] = int(state.get('revision', 0)) + 1
    state['syncing'] = True
    store.save_state(state)
    changed, latest, sample_days = store.merge_samples(samples)
    for metric, point in latest.items():
        previous = state.setdefault('latest', {}).get(metric)
        if not previous or int(point['t']) >= int(previous['t']):
            if previous and point['t'] == previous['t'] and point['value'] is None and previous['value'] is not None:
                continue
            state['latest'][metric] = point
    state['revision'] += 1
    state['syncing'] = False
    state['last_success_at'] = int(time.time())
    state['warnings'] = warnings
    state['last_changed_rows'] = changed
    state['failures'] = 0
    state.pop('last_error', None)
    state.pop('retry_after', None)
    store.save_state(state)
    return changed, sample_days | set(local_days_for_window(start, end))


def reserve_setting(store, state, owner, now):
    today = datetime.fromtimestamp(now, ZONE).date().isoformat()
    checked_at = float(state.get('reserve_checked_at', 0))
    cached_today = state.get('reserve_checked_day') == today and state.get('reserve_soc_pct') is not None
    if cached_today and (state.get('reserve_source') == 'foxess_min_soc_on_grid' or now - checked_at < 3600):
        return float(state['reserve_soc_pct']), state.get('reserve_source', 'foxess_min_soc_on_grid'), False
    fallback = max(0, min(100, float(os.environ.get('RESERVE_SOC_FALLBACK_PCT', '40'))))
    try:
        value = guarded_fox_call(store, state, owner, fetch_reserve_soc)
        source, warning, called = 'foxess_min_soc_on_grid', None, True
    except AppError as exc:
        value, source = fallback, 'configured_fallback'
        called = exc.code != 'FOX_BUDGET_EXHAUSTED'
        warning = f'Reserve 设置读取失败，暂用 {fallback:g}%：{exc.message}'
    state.update(reserve_checked_day=today, reserve_checked_at=int(now),
                 reserve_soc_pct=value, reserve_source=source)
    if warning:
        state['reserve_warning'] = warning
    else:
        state.pop('reserve_warning', None)
    store.save_state(state)
    return value, source, called


def refresh_summary(store, state, owner, day, now, reserve_soc, reserve_source, force_report=False):
    previous = store.get_summary(day)
    cached = previous.get('_report') if previous else None
    fetched_at = int(cached.get('fetched_at', 0)) if isinstance(cached, dict) else 0
    attempted_at = int(previous.get('_report_attempted_at', 0)) if previous else 0
    today = datetime.fromtimestamp(now, ZONE).date()
    needs_report = ((not cached or day == today)
                    and now - max(fetched_at, attempted_at) >= REPORT_REFRESH_SECONDS)
    if force_report and now - max(fetched_at, attempted_at) >= 60:
        needs_report = True
    report, report_called = None, False
    if needs_report:
        try:
            report = guarded_fox_call(store, state, owner, lambda: fetch_report(day))
            report_called = True
            state.pop('report_warning', None)
        except AppError as exc:
            report_called = exc.code != 'FOX_BUDGET_EXHAUSTED'
            state['report_warning'] = ('Fox 日报暂不可用；能量值会优先使用已缓存的官方日报，'
                                       '其余缺失值再使用 raw power 积分：' + exc.message)
            store.save_state(state)
    rows = store.query_day(day)
    summary = build_daily_summary(day, rows, now, report=report, previous=previous,
                                  reserve_soc_pct=reserve_soc, reserve_source=reserve_source)
    if needs_report:
        summary['_report_attempted_at'] = int(now)
    elif previous and previous.get('_report_attempted_at'):
        summary['_report_attempted_at'] = int(previous['_report_attempted_at'])
    summary['warnings'] = [state[key] for key in ('reserve_warning', 'report_warning') if state.get(key)]
    store.save_summary(day, summary)
    state['analytics_last_success_at'] = int(time.time())
    store.save_state(state)
    return report_called


def refresh_summaries(store, state, owner, days, now, force_report=False):
    reserve_soc, reserve_source, reserve_called = reserve_setting(store, state, owner, now)
    calls = int(reserve_called)
    today = datetime.fromtimestamp(now, ZONE).date()
    for day in sorted(set(days)):
        if day <= today:
            calls += int(refresh_summary(store, state, owner, day, now, reserve_soc,
                                         reserve_source, force_report=force_report))
    return calls


def lambda_handler(event, context):
    event = event if isinstance(event, dict) else {}
    if event.get('requestContext'):
        return {'ok': False, 'error': 'COLLECTOR_IS_PRIVATE'}
    action = event.get('action', 'poll')
    if action not in {'poll', 'backfill', 'reconcile'}:
        return {'ok': False, 'error': 'INVALID_ACTION'}
    store, now, owner = get_store(), time.time(), secrets.token_hex(16)
    if not store.acquire(owner, now):
        return {'ok': True, 'skipped': 'collector_already_running'}
    state = store.state()
    windows, changed, analytics_calls = 0, 0, 0
    try:
        if not os.environ.get('FOX_API_KEY', '').strip() or not os.environ.get('FOX_DEVICE_SN', '').strip():
            raise AppError(503, 'FOX_NOT_CONFIGURED', '请设置采集函数的 Fox API key 和逆变器 SN。')
        if action == 'backfill':
            start, end = validate_backfill(event, now)
            if state.get('backfill_next') is not None and int(state['backfill_next']) < int(state['backfill_end']):
                raise AppError(409, 'BACKFILL_ACTIVE', '已有补历史任务运行中，请等它完成后再提交。')
            state.update(backfill_next=start, backfill_end=end, backfill_started_at=int(now))
            store.save_state(state)
        if float(state.get('retry_after', 0)) > now:
            return {'ok': True, 'skipped': 'backoff', 'retry_after': int(state['retry_after'])}

        observed = [int(point['t']) / 1000 for point in state.get('latest', {}).values()]
        anchor = state.get('through') if state.get('catchup') else (max(observed) if observed else state.get('through'))
        start, end = plan_window(anchor, now)
        delta, days = ingest_window(store, state, owner, start, end, context)
        changed += delta
        windows += 1
        analytics_calls += refresh_summaries(store, state, owner, days, now)
        state['through'] = end
        state['catchup'] = end < int(now)
        store.save_state(state)

        local = datetime.fromtimestamp(now, ZONE)
        yesterday = local.date() - timedelta(days=1)
        if (not state.get('reconcile_next') and (local.hour >= 3 or action == 'reconcile')
                and state.get('reconciled_day') != yesterday.isoformat()):
            state.update(reconcile_next=day_start(yesterday), reconcile_end=day_start(local.date()),
                         reconcile_day=yesterday.isoformat())
            store.save_state(state)
        if state.get('reconcile_next') is not None:
            start, target = int(state['reconcile_next']), int(state['reconcile_end'])
            end = min(target, start + 86400)
            delta, days = ingest_window(store, state, owner, start, end, context)
            changed += delta
            windows += 1
            analytics_calls += refresh_summaries(store, state, owner, days, now, force_report=True)
            if end >= target:
                state['reconciled_day'] = state['reconcile_day']
                for key in ('reconcile_next', 'reconcile_end', 'reconcile_day'):
                    state.pop(key, None)
            else:
                state['reconcile_next'] = end
            store.save_state(state)
        elif state.get('backfill_next') is not None and int(state['backfill_next']) < int(state['backfill_end']):
            start = int(state['backfill_next'])
            end = min(int(state['backfill_end']), start + 86400)
            delta, days = ingest_window(store, state, owner, start, end, context)
            changed += delta
            windows += 1
            analytics_calls += refresh_summaries(store, state, owner, days, now, force_report=True)
            state['backfill_next'] = end
            if end >= int(state['backfill_end']):
                state['backfill_finished_at'] = int(time.time())
            store.save_state(state)
        result = {'ok': True, 'windows': windows, 'changed_rows': changed,
                  'summaries_refreshed': True, 'analytics_api_calls': analytics_calls,
                  'through': int(state['through']),
                  'calls_last_24h': int(state.get('calls_last_24h', 0))}
        print(json.dumps(result))
        return result
    except Exception as exc:
        error = exc if isinstance(exc, AppError) else AppError(
            503, 'COLLECTION_FAILED', '采集、汇总或数据库写入失败，请检查采集函数日志和权限。')
        if error.status in {400, 409}:
            return {'ok': False, 'error': error.code, 'message': error.message}
        state['failures'] = int(state.get('failures', 0)) + 1
        delay = 900 if error.code in {'FOX_RATE_LIMIT', 'FOX_BUDGET_EXHAUSTED'} else min(
            3600, 300 * 2 ** min(state['failures'] - 1, 4))
        state.update(last_error={'code': error.code, 'message': error.message},
                     retry_after=int(time.time()) + delay, syncing=False)
        state['revision'] = int(state.get('revision', 0)) + 1
        store.save_state(state)
        print(json.dumps({'ok': False, 'code': error.code, 'exception_type': type(exc).__name__}))
        return {'ok': False, 'error': error.code, 'message': error.message,
                'retry_after': state['retry_after']}
    finally:
        store.release(owner)
