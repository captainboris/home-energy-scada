"""Web-only Passkey ceremonies and AUTH records; no Collector dependency."""
import hashlib
import json
import os
import re
import secrets
from http.cookies import SimpleCookie, CookieError
from urllib.parse import urlsplit

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import AppError
from storage import is_condition_failure

CEREMONY_COOKIE = '__Host-energy_webauthn'
CHALLENGE_SECONDS = 300
GRANT_SECONDS = 600


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def settings():
    if os.environ.get('PASSKEY_ENABLED') != 'true':
        raise AppError(503, 'PASSKEY_DISABLED', 'Passkey 登录尚未启用，请使用密码。')
    origin = os.environ.get('PASSKEY_ORIGIN', '')
    url = urlsplit(origin)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or url.path or url.query or url.fragment or url.netloc != url.hostname
            or not re.fullmatch(r'[a-z0-9.-]+', url.hostname)):
        raise AppError(503, 'PASSKEY_CONFIG_INVALID', '请配置精确的 HTTPS PASSKEY_ORIGIN（无路径或端口）。')
    return origin, url.hostname


def check_origin(event, origin):
    headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
    if headers.get('origin') != origin:
        raise AppError(403, 'ORIGIN_DENIED', '请从此应用自己的网址操作。')


def partition(store):
    return 'AUTH#PASSKEY#' + store.site


def credential_key(raw_id):
    return 'CRED#' + hashlib.sha256(raw_id).hexdigest()


def active_credential(store, key, origin=None):
    record = store.get(partition(store), key)
    if not record or record.get('revoked_at') is not None or (origin and record['origin'] != origin):
        raise AppError(401, 'PASSKEY_INVALID', 'Passkey 无效或已撤销，请使用其他 Passkey 或密码。')
    return record


def rate_limit(store, ip, now):
    # Independent budget: do not double-count two-step ceremonies in password login's budget.
    for name, maximum in [(digest(ip), 20), ('global', 60)]:
        try:
            store.table.update_item(
                Key={'pk': 'AUTH#PASSKEY#RATE', 'sk': f'{int(now // 60)}#{name}'},
                UpdateExpression='SET expires_at = :ttl ADD attempts :one',
                ConditionExpression='attribute_not_exists(attempts) OR attempts < :max',
                ExpressionAttributeValues={':ttl': int(now) + 120, ':one': 1, ':max': maximum})
        except ClientError as exc:
            if not is_condition_failure(exc):
                raise
            raise AppError(429, 'LOGIN_RATE_LIMIT', '尝试次数较多，请一分钟后再试。') from None


def issue_grant(store, purpose, now, origin):
    """Operator-only primitive. No HTTP route can issue grants."""
    if purpose not in {'register', 'manage'}:
        raise ValueError('purpose must be register or manage')
    token = secrets.token_hex(32)
    store.table.put_item(Item={'pk': partition(store), 'sk': 'GRANT#' + digest(token),
                              'purpose': purpose, 'origin': origin,
                              'expires_at': int(now) + GRANT_SECONDS},
                         ConditionExpression='attribute_not_exists(pk)')
    return token


def grant(store, token, purpose, now, origin, consume=True):
    if not isinstance(token, str) or not re.fullmatch(r'[0-9a-f]{64}', token):
        raise AppError(403, 'PASSKEY_PERMISSION', '需要管理员提供有效的一次性许可。')
    key = {'pk': partition(store), 'sk': 'GRANT#' + digest(token)}
    if not consume:
        item = store.get(**key)
        if item and item.get('purpose') == purpose and item.get('origin') == origin and int(item['expires_at']) > now:
            return item
    else:
        try:
            return store.table.delete_item(
                Key=key, ReturnValues='ALL_OLD',
                ConditionExpression='attribute_exists(pk) AND purpose = :purpose AND origin = :origin AND expires_at > :now',
                ExpressionAttributeValues={':purpose': purpose, ':origin': origin, ':now': int(now)})['Attributes']
        except ClientError as exc:
            if not is_condition_failure(exc):
                raise
    raise AppError(403, 'PASSKEY_PERMISSION', '许可已过期、已使用或不适用于此操作。')


def records(store):
    result, cursor = [], None
    while True:
        args = {'KeyConditionExpression': Key('pk').eq(partition(store)) & Key('sk').begins_with('CRED#'),
                'ConsistentRead': True}
        if cursor:
            args['ExclusiveStartKey'] = cursor
        page = store.table.query(**args)
        result.extend(page.get('Items', []))
        cursor = page.get('LastEvaluatedKey')
        if not cursor:
            return result


def profile(store):
    item = store.get(partition(store), 'PROFILE')
    if item:
        return item['user_handle']
    from webauthn.helpers import bytes_to_base64url
    handle = bytes_to_base64url(secrets.token_bytes(32))
    try:
        store.table.put_item(Item={'pk': partition(store), 'sk': 'PROFILE', 'user_handle': handle},
                             ConditionExpression='attribute_not_exists(pk)')
        return handle
    except ClientError as exc:
        if not is_condition_failure(exc):
            raise
        return store.get(partition(store), 'PROFILE')['user_handle']


def new_challenge(store, purpose, now, origin, password_version, session_id=None, deadline=None):
    from webauthn.helpers import bytes_to_base64url
    identifier, binding = secrets.token_hex(32), secrets.token_hex(32)
    item = {'pk': partition(store), 'sk': 'CHALLENGE#' + identifier,
            'challenge': bytes_to_base64url(secrets.token_bytes(32)), 'purpose': purpose,
            'origin': origin, 'password_version': password_version, 'binding': digest(binding),
            'session_id': session_id or '',
            'expires_at': min(int(now) + CHALLENGE_SECONDS, int(deadline or now + CHALLENGE_SECONDS))}
    store.table.put_item(Item=item, ConditionExpression='attribute_not_exists(pk)')
    cookie = f'{CEREMONY_COOKIE}={identifier}.{binding}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age={CHALLENGE_SECONDS}'
    return identifier, item, cookie


def ceremony_cookie(event):
    jar = SimpleCookie()
    try:
        headers = {k.lower(): v for k, v in (event.get('headers') or {}).items()}
        for value in event.get('cookies') or [headers.get('cookie', '')]:
            jar.load(value)
        value = jar[CEREMONY_COOKIE].value
        if re.fullmatch(r'[0-9a-f]{64}\.[0-9a-f]{64}', value):
            return value.split('.')
    except (KeyError, ValueError, TypeError, CookieError):
        pass
    return None, None


def consume_challenge(store, event, body, purpose, now, origin, password_version, session_id=None):
    identifier, binding = ceremony_cookie(event)
    if not identifier or body.get('challenge_id') != identifier:
        raise AppError(400, 'PASSKEY_CHALLENGE', '验证已取消或失效，请重新开始。')
    try:
        return store.table.delete_item(
            Key={'pk': partition(store), 'sk': 'CHALLENGE#' + identifier}, ReturnValues='ALL_OLD',
            ConditionExpression='attribute_exists(pk) AND expires_at > :now AND purpose = :purpose AND origin = :origin AND binding = :binding AND password_version = :version AND session_id = :session',
            ExpressionAttributeValues={':now': int(now), ':purpose': purpose, ':origin': origin,
                                       ':binding': digest(binding), ':version': password_version,
                                       ':session': session_id or ''})['Attributes']
    except ClientError as exc:
        if not is_condition_failure(exc):
            raise
        raise AppError(400, 'PASSKEY_CHALLENGE', '验证已过期或已使用，请重新开始。') from None


def cancel_challenge(store, event):
    identifier, binding = ceremony_cookie(event)
    if identifier:
        try:
            store.table.delete_item(Key={'pk': partition(store), 'sk': 'CHALLENGE#' + identifier},
                                    ConditionExpression='binding = :binding',
                                    ExpressionAttributeValues={':binding': digest(binding)})
        except ClientError as exc:
            if not is_condition_failure(exc):
                raise


def options(store, purpose, now, origin, rp_id, version, session_id=None, permission=None):
    from webauthn import generate_authentication_options, generate_registration_options, options_to_json
    from webauthn.helpers import base64url_to_bytes
    from webauthn.helpers.structs import (AuthenticatorSelectionCriteria, AuthenticatorAttachment,
        ResidentKeyRequirement, UserVerificationRequirement, PublicKeyCredentialDescriptor,
        AttestationConveyancePreference)
    deadline = None
    if purpose == 'register':
        permit = grant(store, permission, 'register', now, origin)
        deadline = permit['expires_at']
        handle = profile(store)
    identifier, pending, cookie = new_challenge(store, purpose, now, origin, version, session_id, deadline)
    if purpose == 'login':
        result = generate_authentication_options(rp_id=rp_id, challenge=base64url_to_bytes(pending['challenge']),
            timeout=120000, user_verification=UserVerificationRequirement.REQUIRED)
    else:
        result = generate_registration_options(rp_id=rp_id, rp_name='Home Energy',
            user_id=base64url_to_bytes(handle), user_name='Home Energy',
            challenge=base64url_to_bytes(pending['challenge']), timeout=120000,
            attestation=AttestationConveyancePreference.NONE,
            authenticator_selection=AuthenticatorSelectionCriteria(
                authenticator_attachment=AuthenticatorAttachment.PLATFORM,
                resident_key=ResidentKeyRequirement.REQUIRED,
                user_verification=UserVerificationRequirement.REQUIRED),
            exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(row['credential_id']))
                                 for row in records(store)])
    return {'challenge_id': identifier, 'publicKey': json.loads(options_to_json(result))}, cookie


def verify(store, event, body, purpose, now, origin, rp_id, version, session_id=None):
    from webauthn import verify_authentication_response, verify_registration_response
    from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
    from webauthn.helpers.exceptions import WebAuthnException
    pending = consume_challenge(store, event, body, purpose, now, origin, version, session_id)
    credential = body.get('credential')
    try:
        if not isinstance(credential, dict):
            raise ValueError()
        client = json.loads(base64url_to_bytes(credential['response']['clientDataJSON']))
        if client.get('crossOrigin', False) is not False or client.get('topOrigin'):
            raise ValueError()
        args = dict(credential=credential, expected_challenge=base64url_to_bytes(pending['challenge']),
                    expected_origin=origin, expected_rp_id=rp_id, require_user_verification=True)
        if purpose == 'register':
            checked = verify_registration_response(**args, require_user_presence=True)
            key = credential_key(checked.credential_id)
            label = body.get('label', '')
            if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
                raise ValueError()
            item = {'pk': partition(store), 'sk': key,
                    'credential_id': bytes_to_base64url(checked.credential_id),
                    'public_key': bytes_to_base64url(checked.credential_public_key),
                    'sign_count': checked.sign_count, 'origin': origin, 'user_handle': profile(store),
                    'label': label.strip(), 'created_at': int(now),
                    'backup_eligible': checked.credential_device_type.value == 'multi_device',
                    'backed_up': checked.credential_backed_up}
            try:
                store.table.put_item(Item=item, ConditionExpression='attribute_not_exists(pk)')
            except ClientError as exc:
                if not is_condition_failure(exc):
                    raise
                raise AppError(409, 'PASSKEY_DUPLICATE', '此 Passkey 已注册（或已撤销），请创建新的 Passkey。') from None
            return {'ok': True}
        raw_id = base64url_to_bytes(credential['rawId'])
        key = credential_key(raw_id)
        record = active_credential(store, key, origin)
        if credential['response'].get('userHandle') != record['user_handle']:
            raise ValueError()
        checked = verify_authentication_response(**args,
            credential_public_key=base64url_to_bytes(record['public_key']),
            credential_current_sign_count=int(record['sign_count']))
        if (checked.credential_device_type.value == 'multi_device') != record['backup_eligible']:
            raise ValueError()
        store.table.update_item(
            Key={'pk': partition(store), 'sk': key},
            UpdateExpression='SET sign_count = :count, backed_up = :backup',
            ConditionExpression='attribute_exists(pk) AND attribute_not_exists(revoked_at) AND sign_count = :old',
            ExpressionAttributeValues={':count': checked.new_sign_count, ':backup': checked.credential_backed_up,
                                       ':old': record['sign_count']})
        return key
    except (WebAuthnException, ValueError, TypeError, KeyError, UnicodeError):
        raise AppError(401, 'PASSKEY_INVALID', 'Passkey 验证失败，请重试或使用密码。') from None
    except ClientError as exc:
        if not is_condition_failure(exc):
            raise
        raise AppError(401, 'PASSKEY_INVALID', 'Passkey 状态已改变，请重新登录。') from None


def manage(store, body, now, origin):
    operation = body.get('operation')
    if operation not in {'list', 'revoke'}:
        raise AppError(400, 'PASSKEY_OPERATION', '不支持此 Passkey 操作。')
    grant(store, body.get('permission'), 'manage', now, origin, consume=operation == 'revoke')
    if operation == 'list':
        return {'credentials': [{'key': row['sk'], 'label': row['label'],
                                 'created_at': int(row['created_at']),
                                 'revoked': row.get('revoked_at') is not None} for row in records(store)]}
    key = body.get('key', '')
    if not isinstance(key, str) or not re.fullmatch(r'CRED#[0-9a-f]{64}', key):
        raise AppError(400, 'PASSKEY_OPERATION', '无效的凭据。')
    try:
        store.table.update_item(Key={'pk': partition(store), 'sk': key},
                                UpdateExpression='SET revoked_at = :now',
                                ConditionExpression='attribute_exists(pk)',
                                ExpressionAttributeValues={':now': int(now)})
    except ClientError as exc:
        if not is_condition_failure(exc):
            raise
        raise AppError(404, 'PASSKEY_NOT_FOUND', '凭据不存在。') from None
    return {'ok': True}
