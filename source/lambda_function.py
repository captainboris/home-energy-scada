"""Public HTML/JS and authenticated database reads. No Fox API client here."""
import base64
import gzip
import hashlib
import hmac
import json
import math
import os
import re
import secrets
import time
import traceback
from datetime import date, datetime, time as daytime, timedelta
from decimal import Decimal
from http.cookies import SimpleCookie, CookieError
from pathlib import Path

from analytics import (POWER_FALLBACKS, build_daily_summary, coverage,
                       finite_number, local_days_for_window, peak,
                       public_summary, reserve_reached)
from common import AppError, GAP_SECONDS, METRICS, VERSION, ZONE, iso
from history_service import boundary_epoch_ms, unified_history
from storage import Store, is_condition_failure
from telemetry_storage import (TelemetryStore, telemetry_health,
                               telemetry_history, telemetry_incremental,
                               telemetry_peaks)

COOKIE = '__Host-energy_session'
IDLE_SECONDS = 1800
ABSOLUTE_SECONDS = 7 * 86400
MAX_RANGE_DAYS = 367
EARLIEST_HISTORY_MS = int(datetime(2020, 1, 1, tzinfo=ZONE).timestamp() * 1000)
ROOT = Path(__file__).parent
FRONTEND_FILENAMES = {
    '/': ('index.html', 'text/html; charset=utf-8'),
    '/index.html': ('index.html', 'text/html; charset=utf-8'),
    '/app.js': ('app.js', 'application/javascript; charset=utf-8'),
    '/daily': ('daily.html', 'text/html; charset=utf-8'),
    '/daily.html': ('daily.html', 'text/html; charset=utf-8'),
    '/daily.js': ('daily.js', 'application/javascript; charset=utf-8'),
    '/shared.js': ('shared.js', 'application/javascript; charset=utf-8'),
    '/shared.css': ('shared.css', 'text/css; charset=utf-8'),
}
FRONTEND_ASSET_TYPES = {
    '.js': 'application/javascript; charset=utf-8',
    '.css': 'text/css; charset=utf-8',
    '.json': 'application/json; charset=utf-8',
    '.svg': 'image/svg+xml',
}
_store = None
_telemetry_store = None
API_VERSION = "0.6.2"

SENSITIVE_ENV_NAMES = ('APP_PASSWORD', 'FOX_API_KEY', 'FOX_API_SECRET',
                       'AUTHORIZATION', 'ACCESS_TOKEN', 'REFRESH_TOKEN')
AUTH_ERROR_STAGES = {
    'SESSION_TOKEN_MISSING': 'session_cookie',
    'TOKEN_INVALID': 'token_validation',
    'TOKEN_EXPIRED': 'token_expiry',
    'SESSION_IDLE': 'idle_expiry',
    'WRONG_PASSWORD': 'password_validation',
    'ORIGIN_DENIED': 'origin_validation',
}


def get_store():
    global _store
    if _store is None:
        _store = Store()
    return _store


def get_telemetry_store():
    global _telemetry_store
    if _telemetry_store is None:
        _telemetry_store = TelemetryStore()
    return _telemetry_store


def configured_date(name, fallback=None):
    """Read a deployment date without leaking it into frontend code."""
    value = os.environ.get(name, '').strip()
    if not value:
        if fallback is None:
            raise AppError(503, 'INSTALLATION_DATE_NOT_CONFIGURED',
                           f'请配置 {name}（YYYY-MM-DD）。')
        return fallback
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise AppError(503, 'INSTALLATION_DATE_INVALID',
                       f'{name} 必须使用 YYYY-MM-DD。') from None
    if parsed.year < 2020:
        raise AppError(503, 'INSTALLATION_DATE_INVALID',
                       f'{name} 不能早于 2020-01-01。')
    return parsed


def installation_dates():
    data_start = configured_date('FOXESS_DATA_START_DATE', date(2020, 1, 1))
    battery_start = configured_date('BATTERY_INSTALL_DATE', data_start)
    return data_start, battery_start


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


def response(status, value, cookies=None, content_type='application/json; charset=utf-8'):
    headers = {'Content-Type': content_type, 'Cache-Control': 'no-store',
               'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'no-referrer',
               'X-Frame-Options': 'DENY',
               'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"}
    body = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, allow_nan=False,
        separators=(',', ':'), default=lambda v: int(v) if isinstance(v, Decimal) and v == int(v) else float(v))
    encoded = False
    compressible = content_type.startswith(('application/json',
                                             'application/javascript',
                                             'text/css'))
    if compressible and len(body.encode()) > 32000:
        body = base64.b64encode(gzip.compress(body.encode(), compresslevel=5)).decode()
        headers['Content-Encoding'] = 'gzip'
        encoded = True
    result = {'statusCode': status, 'headers': headers, 'body': body, 'isBase64Encoded': encoded}
    if cookies:
        result['cookies'] = cookies
    return result


def app_password():
    password = os.environ.get('APP_PASSWORD', '')
    if not 10 <= len(password) <= 256:
        raise AppError(503, 'APP_PASSWORD_NOT_CONFIGURED', '请设置10至256个字符的 APP_PASSWORD。')
    return password


def password_version(password):
    return hashlib.sha256(('energy-session-v2:' + password).encode()).hexdigest()


def json_body(event):
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    if headers.get('content-type', '').split(';')[0].lower() != 'application/json':
        raise AppError(415, 'JSON_REQUIRED', '请求需要使用 application/json。')
    body = event.get('body') or '{}'
    if len(body) > 8192:
        raise AppError(413, 'BODY_TOO_LARGE', '请求内容过大。')
    try:
        raw = base64.b64decode(body, validate=True) if event.get('isBase64Encoded') else body.encode()
        if len(raw) > 4096:
            raise ValueError()
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError()
        return parsed
    except (ValueError, TypeError, UnicodeDecodeError):
        raise AppError(400, 'INVALID_JSON', '无法读取请求 JSON。') from None


def check_origin(event):
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    origin = headers.get('origin')
    domain = event.get('requestContext', {}).get('domainName', '')
    if origin and origin != 'https://' + domain:
        raise AppError(403, 'ORIGIN_DENIED', '请从此应用自己的网址操作。')


def token_details(event):
    jar = SimpleCookie()
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    try:
        for value in event.get('cookies') or [headers.get('cookie', '')]:
            jar.load(value)
        if COOKIE not in jar:
            return None, False, False
        token = jar[COOKIE].value
        if len(token) != 64 or any(c not in '0123456789abcdef' for c in token):
            return None, True, False
        return hashlib.sha256(token.encode()).hexdigest(), True, True
    except (KeyError, ValueError, CookieError, TypeError):
        return None, True, False


def token_from(event):
    """Compatibility helper used by logout; never returns the raw cookie."""
    return token_details(event)[0]


def require_session(event, password, now, store):
    identifier, present, valid = token_details(event)
    if not present:
        raise AppError(401, 'SESSION_TOKEN_MISSING', '请输入访问密码。')
    if not valid:
        raise AppError(401, 'TOKEN_INVALID', '会话无效，请重新登录。')
    session = store.get('AUTH#SESSION', identifier)
    if not session or session.get('password_version') != password_version(password):
        raise AppError(401, 'TOKEN_INVALID', '会话无效，请重新登录。')
    if now >= int(session['absolute_expires']):
        raise AppError(401, 'TOKEN_EXPIRED', '会话已过期，请重新登录。')
    if now - float(session['last_activity']) >= IDLE_SECONDS:
        raise AppError(401, 'SESSION_IDLE', '超过30分钟没有操作，已自动退出。')
    return identifier, session


def session_payload(session):
    return {'ok': True, 'last_activity': int(session['last_activity']),
            'idle_deadline': min(int(session['last_activity']) + IDLE_SECONDS, int(session['absolute_expires'])),
            'idle_seconds': IDLE_SECONDS}


def login(event, password, now, store):
    body = json_body(event)
    provided = body.get('password', '')
    ip = event.get('requestContext', {}).get('http', {}).get('sourceIp', 'unknown')
    store.login_attempt(hashlib.sha256(ip.encode()).hexdigest(), now)
    if not isinstance(provided, str) or not hmac.compare_digest(
            hashlib.sha256(provided.encode()).digest(), hashlib.sha256(password.encode()).digest()):
        raise AppError(401, 'WRONG_PASSWORD', '访问密码不正确。')
    # Independent random session secret; shortening the login password cannot forge a cookie.
    token = secrets.token_hex(32)
    session = {'pk': 'AUTH#SESSION', 'sk': hashlib.sha256(token.encode()).hexdigest(),
               'password_version': password_version(password), 'last_activity': int(now),
               'absolute_expires': int(now) + ABSOLUTE_SECONDS, 'expires_at': int(now) + IDLE_SECONDS}
    store.put(session)
    cookie = f'{COOKIE}={token}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={ABSOLUTE_SECONDS}'
    return response(200, session_payload(session), [cookie])


def bounds(params, now):
    preset = params.get('range', 'today')
    today = datetime.fromtimestamp(now, ZONE).date()
    if params.get('from_ms') is not None or params.get('to_ms') is not None:
        try:
            begin = int(params['from_ms'])
            finish = int(params['to_ms'])
        except (KeyError, TypeError, ValueError, OverflowError):
            raise AppError(400, 'INVALID_DATE', 'from_ms / to_ms 必须是有效的毫秒时间戳。') from None
        if begin < EARLIEST_HISTORY_MS or finish <= begin:
            raise AppError(400, 'INVALID_DATE', '时间范围必须从 2020 年以后开始，且结束时间晚于开始时间。')
        if finish - begin > MAX_RANGE_DAYS * 86400 * 1000:
            raise AppError(400, 'RANGE_TOO_LONG', '每次最多查看367天。')
        start_local = datetime.fromtimestamp(begin / 1000, ZONE)
        end_local = datetime.fromtimestamp((finish - 1) / 1000, ZONE)
        return {'preset': preset, 'start_date': start_local.date().isoformat(),
                'end_date': end_local.date().isoformat(),
                'start_at': start_local.isoformat(timespec='seconds'),
                'end_at': datetime.fromtimestamp(finish / 1000, ZONE).isoformat(timespec='seconds'),
                'start_ms': begin, 'end_ms': finish, 'key': f'{begin}/{finish}'}
    if preset == 'today':
        start, end = today, today
    elif preset == 'yesterday':
        start = end = today - timedelta(days=1)
    elif preset == 'week':
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
    elif preset == 'month':
        start = today.replace(day=1)
        following = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
        end = following - timedelta(days=1)
    elif preset == 'custom':
        try:
            start, end = date.fromisoformat(params['start']), date.fromisoformat(params['end'])
        except (KeyError, TypeError, ValueError):
            raise AppError(400, 'INVALID_DATE', '请填写完整的开始和结束日期。') from None
    else:
        raise AppError(400, 'INVALID_RANGE', '不支持此时间范围。')
    if not 0 <= (end - start).days < MAX_RANGE_DAYS:
        raise AppError(400, 'RANGE_TOO_LONG', '结束日期不得早于开始日期，每次最多查看367天。')
    begin = int(datetime.combine(start, daytime.min, ZONE).timestamp() * 1000)
    finish = int(datetime.combine(end + timedelta(days=1), daytime.min, ZONE).timestamp() * 1000)
    return {'preset': preset, 'start_date': start.isoformat(), 'end_date': end.isoformat(),
            'start_at': datetime.fromtimestamp(begin / 1000, ZONE).isoformat(timespec='seconds'),
            'end_at': datetime.fromtimestamp(finish / 1000, ZONE).isoformat(timespec='seconds'),
            'start_ms': begin, 'end_ms': finish, 'key': f'{begin}/{finish}'}


def history_data(params, now, store, window=None):
    window = window or bounds(params, now)
    state = store.state()
    warnings = []
    if not state.get('last_success_at'):
        warnings.append('历史库还没有完成首次采集。请先运行采集函数，并启用定时任务。')
    elif now - int(state['last_success_at']) > 900:
        warnings.append('后台超过15分钟未成功同步，请检查采集状态。已有历史仍可查看。')
    if state.get('last_error'):
        warnings.append(state['last_error']['message'])
    if state.get('syncing'):
        warnings.append('后台正在写入数据，下次刷新会继续更新。')
    for key in ('reserve_warning', 'report_warning'):
        if state.get(key):
            warnings.append(state[key])
    warnings.extend(state.get('warnings', []))
    latest = state.get('latest', {})
    valid_times = [int(v['t']) for v in latest.values() if v.get('value') is not None]
    data = {'source': 'foxess', 'timezone': 'Australia/Melbourne', 'range': window,
            'revision': int(state.get('revision', 0)), 'latest': latest,
            'latest_observed_at': iso(max(valid_times) / 1000) if valid_times else None,
            'max_gap_seconds': GAP_SECONDS, 'warnings': warnings,
            'collector': {'last_success_at': iso(int(state['last_success_at'])) if state.get('last_success_at') else None,
                'cadence_seconds': int(os.environ.get('COLLECT_INTERVAL_SECONDS', '300')),
                'calls_last_24h': store.recent_call_count(now),
                'budget': int(os.environ.get('FOX_CALLS_PER_DAY', '1000')),
                'catching_up': bool(state.get('through') and now - int(state['through']) > 1200),
                'backfill_active': bool(state.get('backfill_next') is not None and int(state['backfill_next']) < int(state['backfill_end']))}}
    unchanged = params.get('known_range') == window['key'] and params.get('known_revision') == str(data['revision'])
    data['not_modified'] = bool(unchanged and params.get('force') != '1' and not state.get('syncing'))
    if not data['not_modified']:
        rows = store.query_rows(window['start_ms'], min(window['end_ms'], int(now * 1000) + 1))
        series = {metric: {'metric': metric, 'unit': unit, 'points': []} for metric, unit in METRICS.values()}
        for row in rows:
            stamp = int(row['epoch_ms'])
            for metric in series:
                series[metric]['points'].append([stamp, row.get(metric)])
        data['series'] = list(series.values())
    # This time describes the successful DB read, never the original measurement.
    data['checked_at'] = iso(time.time())
    return data


def history(params, now, store):
    return response(200, {'data': history_data(params, now, store)})


def hybrid_history(params, now, store):
    window = bounds(params, now)

    def read_legacy(segment):
        # A unified initial load always needs the real points for its clipped
        # legacy segment; conditional revision responses remain available on
        # the backwards-compatible /api/history endpoint.
        return history_data({**params, 'force': '1'}, now, store, segment)

    boundary_ms = boundary_epoch_ms()
    fast_start = max(int(window['start_ms']), boundary_ms)
    needs_fast = (int(window['end_ms']) > fast_start
                  and int(window['end_ms']) - int(window['start_ms']) <= 367 * 86400 * 1000)
    telemetry_store = get_telemetry_store() if needs_fast else None
    data = unified_history(params, now, window, read_legacy, telemetry_store)
    return response(200, {'data': data})


def live_history(params, now):
    data = telemetry_incremental(
        params, now, get_telemetry_store(), minimum_ms=boundary_epoch_ms())
    return response(200, {'data': data})


def fast_telemetry_history(params, now):
    window = bounds(params, now)
    data = telemetry_history(params, now, window, get_telemetry_store())
    return response(200, {'data': data})


def fast_telemetry_health():
    return response(200, {'data': telemetry_health(get_telemetry_store())})


def daily_summary(params, now, store):
    today = datetime.fromtimestamp(now, ZONE).date()
    data_start, battery_start = installation_dates()
    try:
        selected = date.fromisoformat(params.get('date', today.isoformat()))
    except (TypeError, ValueError):
        raise AppError(400, 'INVALID_DATE', 'date 必须使用 YYYY-MM-DD。') from None
    if selected > today or selected.year < 2020:
        raise AppError(400, 'INVALID_DATE', 'Energy Analytics 只能查询今天或过去日期。')
    item = store.get_summary(selected) if selected >= data_start else None
    if not item and selected >= data_start:
        state = store.state()
        item = build_daily_summary(
            selected, store.query_day(selected), now,
            reserve_soc_pct=state.get('reserve_soc_pct'),
            reserve_source=state.get('reserve_source', 'configured_fallback'))
        item['warnings'] = ([] if selected == today else
                            ['该日期缺少缓存的 FoxESS 官方日报。'])
    data = public_summary(item) or {
        'date': selected.isoformat(), 'timezone': 'Australia/Melbourne',
        'energy': {metric: None for metric in POWER_FALLBACKS},
        'performance': {'self_sufficiency_pct': None},
        'peaks': {name: {'kw': None, 'time': None}
                  for name in ('pv', 'load', 'grid_import', 'grid_export')},
        'battery': {'reserve_soc_pct': None, 'reserve_reached_time': None},
        'peak_period': {'grid_import_18_21_kwh': None},
        'data_quality': {'raw_coverage_pct': None, 'raw_samples': 0,
                         'expected_samples': 0},
        'metric_sources': {'energy': {metric: 'not_applicable_before_data_start'
                                     for metric in POWER_FALLBACKS}},
        'warnings': [],
    }
    battery_applicable = selected >= battery_start and selected >= data_start
    if not battery_applicable:
        for metric in ('battery_charge_kwh', 'battery_discharge_kwh'):
            data.setdefault('energy', {})[metric] = None
            data.setdefault('metric_sources', {}).setdefault('energy', {})[metric] = (
                'not_applicable_before_battery_install')
        data['battery'] = {'reserve_soc_pct': None, 'reserve_reached_time': None,
                           'minimum_soc_pct': None, 'minimum_soc_time': None,
                           'applicable': False}
    else:
        data.setdefault('battery', {})['applicable'] = True
    data['availability'] = {
        'foxess_data_start_date': data_start.isoformat(),
        'battery_install_date': battery_start.isoformat(),
        'data_applicable': selected >= data_start,
        'battery_applicable': battery_applicable,
    }
    data['checked_at'] = iso(time.time())
    return response(200, {'data': data})


def range_summary(params, now, store):
    """Aggregate official reports and raw analytics for an exact range.

    Installation dates define when data is expected. The current local date is
    allowed to be partial; only missing completed dates generate warnings.
    """
    window = bounds(params, now)
    data_start, battery_start = installation_dates()
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
                get_telemetry_store())
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
    return response(200, {'data': data})


def frontend_file(path):
    if path in FRONTEND_FILENAMES:
        filename, content_type = FRONTEND_FILENAMES[path]
    elif (path.startswith('/assets/')
          and re.fullmatch(r'/assets/[A-Za-z0-9._/-]+', path)
          and '..' not in path.split('/')):
        filename = path.lstrip('/')
        content_type = FRONTEND_ASSET_TYPES.get(Path(filename).suffix)
        if not content_type:
            raise AppError(404, 'NOT_FOUND', '没有这个静态文件。')
    else:
        raise AppError(404, 'NOT_FOUND', '没有这个静态文件。')
    configured = os.environ.get('FRONTEND_ROOT')
    roots = ([Path(configured)] if configured else []) + [Path('/opt'), ROOT]
    for root in roots:
        candidate = root / filename
        if candidate.is_file():
            result = response(200, candidate.read_text(encoding='utf-8'), content_type=content_type)
            if path.startswith('/assets/'):
                result['headers']['Cache-Control'] = 'public, max-age=31536000, immutable'
            return result
    raise AppError(503, 'FRONTEND_NOT_DEPLOYED', '前端静态层尚未部署到 Web Lambda。')


def safe_log_text(value):
    text = str(value or '')[:2000]
    for name in SENSITIVE_ENV_NAMES:
        secret = os.environ.get(name, '')
        if secret:
            text = text.replace(secret, '[REDACTED]')
    return re.sub(
        r'(?i)(authorization|password|api[_ -]?key|api[_ -]?secret|refresh[_ -]?token)\s*[:=]\s*[^\s,;]+',
        r'\1=[REDACTED]', text)


def request_trace(event, context):
    request = event.get('requestContext', {}).get('http', {})
    path = event.get('rawPath') or request.get('path', '/')
    method = request.get('method', 'GET').upper()
    request_id = (getattr(context, 'aws_request_id', None)
                  or event.get('requestContext', {}).get('requestId')
                  or secrets.token_hex(12))
    headers = {str(key).lower(): value
               for key, value in (event.get('headers') or {}).items()}
    supplied_correlation = str(headers.get('x-correlation-id', ''))
    correlation_id = (supplied_correlation
                      if re.fullmatch(r'[A-Za-z0-9._:-]{1,100}', supplied_correlation)
                      else request_id)
    return {
        'event': 'api_request',
        'request_id': request_id,
        'correlation_id': correlation_id,
        'route': path,
        'http_method': method,
        'status': None,
        'internal_error_code': None,
        'auth_stage': 'not_started',
        'session_token_present': token_details(event)[1],
        'upstream_service': None,
        'upstream_http_status': None,
        'exception_type': None,
        'exception_message': None,
        'duration_ms': None,
    }


def dispatch(event, context, trace):
    now = time.time()
    path = trace['route']
    method = trace['http_method']
    trace['auth_stage'] = 'not_required'
    if method == 'GET' and path == '/api/health':
        return response(200, {'ok': True, 'version': API_VERSION,
                              'rest_core_version': VERSION,
                              'source': 'dynamodb'})
    if method == 'GET' and (path in FRONTEND_FILENAMES or path.startswith('/assets/')):
        return frontend_file(path)
    if path == '/favicon.ico':
        return response(204, '', content_type='text/plain')

    password, store = app_password(), get_store()
    if method == 'POST':
        trace['auth_stage'] = 'origin_validation'
        check_origin(event)
    if method == 'POST' and path == '/api/login':
        trace['auth_stage'] = 'password_validation'
        result = login(event, password, now, store)
        trace['auth_stage'] = 'authenticated'
        return result
    if method == 'POST' and path == '/api/logout':
        trace['auth_stage'] = 'logout'
        identifier = token_from(event)
        if identifier:
            store.table.delete_item(Key={'pk': 'AUTH#SESSION', 'sk': identifier})
        return response(200, {'ok': True},
                        [f'{COOKIE}=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0'])

    trace['auth_stage'] = 'session_validation'
    identifier, session = require_session(event, password, now, store)
    trace['auth_stage'] = 'authenticated'
    if method == 'GET' and path == '/api/session':
        return response(200, session_payload(session))
    if method == 'POST' and path == '/api/activity':
        idle = json_body(event).get('idle_seconds', 0)
        if (isinstance(idle, bool) or not isinstance(idle, (int, float))
                or not math.isfinite(idle) or not 0 <= idle <= 60):
            raise AppError(400, 'INVALID_ACTIVITY', '无效的操作时间。')
        active = int(now - idle)
        try:
            store.table.update_item(
                Key={'pk': 'AUTH#SESSION', 'sk': identifier},
                UpdateExpression='SET last_activity = :active, expires_at = :expires',
                ConditionExpression='attribute_exists(pk) AND last_activity < :active',
                ExpressionAttributeValues={
                    ':active': active,
                    ':expires': min(active + IDLE_SECONDS,
                                    int(session['absolute_expires']))})
            session['last_activity'] = active
        except Exception as exc:
            if not is_condition_failure(exc):
                raise
            # A logout must never be undone by an in-flight activity request.
            _, session = require_session(event, password, time.time(), store)
        return response(200, session_payload(session))
    if method == 'GET' and path == '/api/history':
        return history(event.get('queryStringParameters') or {}, now, store)
    if method == 'GET' and path in {'/api/history/unified', '/history/unified'}:
        trace['upstream_service'] = 'dynamodb_hybrid_historian'
        return hybrid_history(event.get('queryStringParameters') or {}, now, store)
    if method == 'GET' and path in {'/api/history/live', '/history/live'}:
        trace['upstream_service'] = 'dynamodb_fast_telemetry'
        return live_history(event.get('queryStringParameters') or {}, now)
    if method == 'GET' and path in {'/api/telemetry/history', '/telemetry/history'}:
        trace['upstream_service'] = 'dynamodb_fast_telemetry'
        return fast_telemetry_history(event.get('queryStringParameters') or {}, now)
    if method == 'GET' and path in {'/api/telemetry/health', '/telemetry/health'}:
        trace['upstream_service'] = 'dynamodb_fast_telemetry'
        return fast_telemetry_health()
    if method == 'GET' and path in {'/api/summary/daily', '/summary/daily'}:
        return daily_summary(event.get('queryStringParameters') or {}, now, store)
    if method == 'GET' and path in {'/api/summary/range', '/summary/range'}:
        return range_summary(event.get('queryStringParameters') or {}, now, store)
    raise AppError(404, 'NOT_FOUND', '没有这个接口。')


def lambda_handler(event, context):
    started = time.perf_counter()
    event = event if isinstance(event, dict) else {}
    trace = request_trace(event, context)
    try:
        result = dispatch(event, context, trace)
    except AppError as exc:
        trace.update(status=exc.status, internal_error_code=exc.code,
                     auth_stage=AUTH_ERROR_STAGES.get(exc.code,
                                                      trace['auth_stage']),
                     exception_type=type(exc).__name__,
                     exception_message=safe_log_text(exc.message))
        result = response(exc.status, {'error': {
            'code': exc.code, 'message': exc.message,
            'request_id': trace['request_id']}})
    except Exception as exc:
        trace.update(status=503, internal_error_code='WEB_FAILED',
                     exception_type=type(exc).__name__,
                     exception_message=safe_log_text(exc),
                     stack_trace=safe_log_text(traceback.format_exc()))
        result = response(503, {'error': {
            'code': 'WEB_FAILED',
            'message': '无法读取历史库，请使用 Request ID 检查网页函数日志。',
            'request_id': trace['request_id']}})
    trace['status'] = int(result.get('statusCode', trace.get('status') or 500))
    trace['duration_ms'] = round((time.perf_counter() - started) * 1000, 2)
    result.setdefault('headers', {})['X-Request-ID'] = trace['request_id']
    result['headers']['X-Correlation-ID'] = trace['correlation_id']
    print(json.dumps(trace, ensure_ascii=False, separators=(',', ':')))
    return result
