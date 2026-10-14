"""Real WebAuthn library, dynamically signed fixtures, fake clock and moto only."""
import contextlib
import copy
import io
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import patch

from moto import mock_aws
import boto3
import lambda_function as web
import passkeys
from common import AppError
from storage import Store
from test_backend import event, decode, NOW
from passkey_fixtures import Authenticator
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url


class PasskeyTests(unittest.TestCase):
    def setUp(self):
        self.aws = mock_aws(); self.aws.start()
        self.env = patch.dict(os.environ, {'TABLE_NAME': 'passkey-test', 'APP_PASSWORD': '1234567890',
                    'PASSKEY_ENABLED': 'true', 'PASSKEY_ORIGIN': 'https://energy.test'}); self.env.start()
        self.table = boto3.resource('dynamodb').create_table(TableName='passkey-test',
                    AttributeDefinitions=[{'AttributeName': 'pk', 'AttributeType': 'S'}, {'AttributeName': 'sk', 'AttributeType': 'S'}],
                    KeySchema=[{'AttributeName': 'pk', 'KeyType': 'HASH'}, {'AttributeName': 'sk', 'KeyType': 'RANGE'}],
                    BillingMode='PAY_PER_REQUEST')
        self.store = Store(self.table, 'home')
        self.store_patch = patch.object(web, 'get_store', return_value=self.store); self.store_patch.start()
        self.clock = patch('time.time', return_value=NOW); self.clock.start()
        self.logs = io.StringIO(); self.output = contextlib.redirect_stdout(self.logs); self.output.__enter__()
        result = self.call('/api/login', {'password': '1234567890'})
        self.password_cookie = result['cookies'][0].split(';')[0]

    def tearDown(self):
        self.output.__exit__(None, None, None); self.clock.stop(); self.store_patch.stop(); self.env.stop(); self.aws.stop()

    def call(self, path, body=None, cookies=(), method='POST', origin='https://energy.test'):
        request = event(path, method, body)
        request['headers']['origin'] = origin
        request['cookies'] = list(cookies)
        return web.lambda_handler(request, None)

    def permit(self, purpose='register'):
        return passkeys.issue_grant(self.store, purpose, NOW, 'https://energy.test')

    def prepare(self, purpose='login', cookie=None):
        body = {'permission': self.permit()} if purpose == 'register' else {}
        result = self.call('/api/passkey/' + purpose + '/options', body,
                           [cookie or self.password_cookie] if purpose == 'register' else [])
        self.assertEqual(result['statusCode'], 200, result)
        return decode(result), result['cookies'][0].split(';')[0]

    def register(self, authenticator=None, label='iPhone', cookie=None):
        authenticator = authenticator or Authenticator()
        options, ceremony = self.prepare('register', cookie)
        credential = authenticator.response(options, kind='register')
        result = self.call('/api/passkey/register/verify', {'challenge_id': options['challenge_id'],
                          'credential': credential, 'label': label}, [cookie or self.password_cookie, ceremony])
        self.assertEqual(result['statusCode'], 200, result)
        return authenticator

    def login(self, authenticator, **kwargs):
        options, ceremony = self.prepare()
        credential = authenticator.response(options, user_handle=passkeys.profile(self.store), **kwargs)
        return self.call('/api/passkey/login/verify', {'challenge_id': options['challenge_id'],
                         'credential': credential}, [ceremony])

    def test_register_login_real_signature_multiple_keys_and_same_session_contract(self):
        first = self.register(); second = self.register(label='Mac')
        self.assertEqual(len(passkeys.records(self.store)), 2)
        for authenticator in [first, second]:
            result = self.login(authenticator)
            self.assertEqual(result['statusCode'], 200)
            self.assertEqual(decode(result), {'ok': True, 'last_activity': int(NOW),
                             'idle_deadline': int(NOW) + 1800, 'idle_seconds': 1800})
            self.assertIn('HttpOnly; Secure; SameSite=Strict; Max-Age=604800', result['cookies'][0])
            cookie = result['cookies'][0].split(';')[0]
            self.assertEqual(self.call('/api/session', cookies=[cookie], method='GET')['statusCode'], 200)
            # An approved Passkey Session may use a new independent grant to enroll another key.
            if authenticator is second:
                self.register(label='Third', cookie=cookie)

    def test_shared_password_does_not_authorize_registration_listing_or_revocation(self):
        for path, body in [('/api/passkey/register/options', {}),
                           ('/api/passkey/manage', {'operation': 'list'}),
                           ('/api/passkey/manage', {'operation': 'revoke', 'key': 'CRED#' + 'a'*64})]:
            result = self.call(path, body, [self.password_cookie])
            self.assertEqual(result['statusCode'], 403)
        permit = self.permit()
        self.assertEqual(self.call('/api/passkey/register/options', {'permission': permit})['statusCode'], 401)
        wrong = self.permit('manage')
        self.assertEqual(self.call('/api/passkey/register/options', {'permission': wrong}, [self.password_cookie])['statusCode'], 403)

    def test_duplicate_is_not_overwritten_and_excluded(self):
        authenticator = self.register()
        before = copy.deepcopy(passkeys.records(self.store)[0])
        options, ceremony = self.prepare('register')
        self.assertEqual(options['publicKey']['excludeCredentials'][0]['id'], before['credential_id'])
        result = self.call('/api/passkey/register/verify', {'challenge_id': options['challenge_id'],
                          'credential': authenticator.response(options, kind='register'), 'label': 'overwrite'},
                          [self.password_cookie, ceremony])
        self.assertEqual(result['statusCode'], 409)
        self.assertEqual(passkeys.records(self.store)[0], before)

    def test_revoke_requires_manage_grant_and_invalidates_existing_passkey_session(self):
        authenticator = self.register(); key = passkeys.credential_key(authenticator.id)
        session = self.login(authenticator)['cookies'][0].split(';')[0]
        permission = self.permit('manage')
        listing = self.call('/api/passkey/manage', {'operation': 'list', 'permission': permission}, [self.password_cookie])
        self.assertEqual(decode(listing)['credentials'][0]['key'], key)
        result = self.call('/api/passkey/manage', {'operation': 'revoke', 'permission': permission, 'key': key}, [self.password_cookie])
        self.assertEqual(result['statusCode'], 200)
        self.assertEqual(self.call('/api/session', cookies=[session], method='GET')['statusCode'], 401)
        self.assertEqual(self.login(authenticator)['statusCode'], 401)
        self.assertEqual(self.call('/api/passkey/manage', {'operation': 'revoke', 'permission': permission, 'key': key}, [self.password_cookie])['statusCode'], 403)
        self.assertEqual(self.call('/api/session', cookies=[self.password_cookie], method='GET')['statusCode'], 200)

    def test_grant_expiry_challenge_expiry_and_replay(self):
        permission = self.permit()
        with patch('time.time', return_value=NOW + 600):
            self.assertEqual(self.call('/api/passkey/register/options', {'permission': permission}, [self.password_cookie])['statusCode'], 403)
        authenticator = self.register(); options, ceremony = self.prepare()
        body = {'challenge_id': options['challenge_id'], 'credential': authenticator.response(options, user_handle=passkeys.profile(self.store))}
        with patch('time.time', return_value=NOW + 300):
            self.assertEqual(self.call('/api/passkey/login/verify', body, [ceremony])['statusCode'], 400)
        options, ceremony = self.prepare()
        body = {'challenge_id': options['challenge_id'], 'credential': authenticator.response(options, user_handle=passkeys.profile(self.store))}
        self.assertEqual(self.call('/api/passkey/login/verify', body, [ceremony])['statusCode'], 200)
        self.assertEqual(self.call('/api/passkey/login/verify', body, [ceremony])['statusCode'], 400)

    def test_atomic_challenge_and_grant_consumption(self):
        options, cookie = self.prepare(); request = event('/api/passkey/login/verify'); request['cookies'] = [cookie]
        barrier = Barrier(2)
        def consume():
            barrier.wait()
            try:
                passkeys.consume_challenge(self.store, request, {'challenge_id': options['challenge_id']},
                    'login', NOW, 'https://energy.test', web.password_version('1234567890'))
                return True
            except AppError: return False
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: consume(), range(2)))
        self.assertEqual(sorted(results), [False, True])
        permission = self.permit(); barrier = Barrier(2)
        def consume_grant():
            barrier.wait()
            try: passkeys.grant(self.store, permission, 'register', NOW, 'https://energy.test'); return True
            except AppError: return False
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda _: consume_grant(), range(2)))
        self.assertEqual(sorted(results), [False, True])

    def test_origin_rp_uv_signature_userhandle_and_crossorigin_fail_closed(self):
        authenticator = self.register()
        for change in [{'origin': 'https://evil.test'}, {'rp_id': 'evil.test'}, {'uv': False}, {'cross_origin': True}]:
            with self.subTest(change=change):
                self.assertEqual(self.login(authenticator, **change)['statusCode'], 401)
        for field in ['signature', 'userHandle', 'id', 'challenge']:
            with self.subTest(field=field):
                options, ceremony = self.prepare()
                credential = authenticator.response(options, user_handle=passkeys.profile(self.store))
                if field == 'signature': credential['response']['signature'] = bytes_to_base64url(b'bad')
                elif field == 'userHandle': credential['response']['userHandle'] = bytes_to_base64url(b'wrong')
                elif field == 'id': credential['id'] = bytes_to_base64url(b'wrong')
                else:
                    client = json.loads(base64url_to_bytes(credential['response']['clientDataJSON'])); client['challenge'] = 'wrong'
                    credential['response']['clientDataJSON'] = bytes_to_base64url(json.dumps(client).encode())
                self.assertEqual(self.call('/api/passkey/login/verify', {'challenge_id': options['challenge_id'], 'credential': credential}, [ceremony])['statusCode'], 401)
        self.assertEqual(self.call('/api/passkey/login/options', origin='')['statusCode'], 403)
        self.assertEqual(self.call('/api/passkey/login/options', origin='https://evil.test')['statusCode'], 403)

    def test_registration_uv_rp_origin_and_malformed_payload_fail(self):
        for change in [{'uv': False}, {'rp_id': 'evil.test'}, {'origin': 'https://evil.test'}, {'cross_origin': True}]:
            options, ceremony = self.prepare('register')
            result = self.call('/api/passkey/register/verify', {'challenge_id': options['challenge_id'],
                              'credential': Authenticator().response(options, kind='register', **change), 'label': 'test'},
                              [self.password_cookie, ceremony])
            self.assertEqual(result['statusCode'], 401)
        self.assertEqual(passkeys.records(self.store), [])

    def test_browser_and_session_binding_logout_and_password_rotation(self):
        authenticator = self.register(); options, ceremony = self.prepare()
        body = {'challenge_id': options['challenge_id'], 'credential': authenticator.response(options, user_handle=passkeys.profile(self.store))}
        self.assertEqual(self.call('/api/passkey/login/verify', body)['statusCode'], 400)
        self.call('/api/logout', cookies=[ceremony])
        self.assertEqual(self.call('/api/passkey/login/verify', body, [ceremony])['statusCode'], 400)
        options, ceremony = self.prepare('register')
        second_cookie = self.call('/api/login', {'password': '1234567890'})['cookies'][0].split(';')[0]
        body = {'challenge_id': options['challenge_id'], 'credential': Authenticator().response(options, kind='register'), 'label': 'test'}
        self.assertEqual(self.call('/api/passkey/register/verify', body, [second_cookie, ceremony])['statusCode'], 400)
        result = self.login(authenticator); cookie = result['cookies'][0].split(';')[0]
        with patch.dict(os.environ, APP_PASSWORD='changed-password'):
            self.assertEqual(self.call('/api/session', cookies=[cookie], method='GET')['statusCode'], 401)
            # The credential survives password rotation, but signs a newly issued Session.
            self.assertEqual(self.login(authenticator)['statusCode'], 200)

    def test_idle_absolute_and_polling_session_semantics(self):
        authenticator = self.register(); result = self.login(authenticator); cookie = result['cookies'][0].split(';')[0]
        with patch('time.time', return_value=NOW + 1799):
            self.assertEqual(self.call('/api/session', cookies=[cookie], method='GET')['statusCode'], 200)
        with patch('time.time', return_value=NOW + 1800):
            self.assertEqual(decode(self.call('/api/session', cookies=[cookie], method='GET'))['error']['code'], 'SESSION_IDLE')
        identifier = web.token_from({'cookies': [cookie]})
        self.table.update_item(Key={'pk': 'AUTH#SESSION', 'sk': identifier},
            UpdateExpression='SET last_activity = :last', ExpressionAttributeValues={':last': int(NOW) + 604799})
        with patch('time.time', return_value=NOW + 604800):
            self.assertEqual(decode(self.call('/api/session', cookies=[cookie], method='GET'))['error']['code'], 'TOKEN_EXPIRED')

    def test_disabled_feature_config_body_limits_and_secret_logging(self):
        with patch.dict(os.environ, PASSKEY_ENABLED='false'):
            self.assertEqual(self.call('/api/passkey/login/options')['statusCode'], 503)
            self.assertEqual(self.call('/api/login', {'password': '1234567890'})['statusCode'], 200)
        for origin in ['', 'http://energy.test', 'https://energy.test/', 'https://energy.test.evil/path']:
            with patch.dict(os.environ, PASSKEY_ORIGIN=origin):
                self.assertEqual(self.call('/api/passkey/login/options')['statusCode'], 503)
        permission = self.permit()
        self.call('/api/passkey/register/options', {'permission': permission}, [self.password_cookie])
        self.assertNotIn(permission, self.logs.getvalue())
        self.assertEqual(self.call('/api/passkey/login/verify', {'padding': 'x'*17000})['statusCode'], 413)

    def test_counter_zero_supported_nonzero_replay_rejected_and_rate_limit(self):
        authenticator = self.register()
        self.assertEqual(self.login(authenticator)['statusCode'], 200)
        self.assertEqual(self.login(authenticator)['statusCode'], 200)
        self.assertEqual(self.login(authenticator, count=1)['statusCode'], 200)
        self.assertEqual(self.login(authenticator, count=1)['statusCode'], 401)
        with patch('time.time', return_value=NOW + 60):
            for _ in range(20): self.assertEqual(self.call('/api/passkey/login/options')['statusCode'], 200)
            self.assertEqual(self.call('/api/passkey/login/options')['statusCode'], 429)

    def test_passkey_logout_activity_and_feature_kill_switch(self):
        authenticator = self.register()
        cookie = self.login(authenticator)['cookies'][0].split(';')[0]
        with patch('time.time', return_value=NOW + 1000):
            self.assertEqual(self.call('/api/activity', {'idle_seconds': 5}, [cookie])['statusCode'], 200)
        with patch('time.time', return_value=NOW + 2000):
            self.assertEqual(self.call('/api/session', cookies=[cookie], method='GET')['statusCode'], 200)
        self.assertEqual(self.call('/api/logout', cookies=[cookie])['statusCode'], 200)
        self.assertEqual(self.call('/api/activity', {'idle_seconds': 0}, [cookie])['statusCode'], 401)
        cookie = self.login(authenticator)['cookies'][0].split(';')[0]
        with patch.dict(os.environ, PASSKEY_ENABLED='false'):
            self.assertEqual(self.call('/api/session', cookies=[cookie], method='GET')['statusCode'], 401)
            self.assertEqual(self.call('/api/session', cookies=[self.password_cookie], method='GET')['statusCode'], 200)

    def test_browser_binding_wrong_nonce_and_register_after_logout(self):
        authenticator = self.register(); options, ceremony = self.prepare()
        body = {'challenge_id': options['challenge_id'], 'credential': authenticator.response(options, user_handle=passkeys.profile(self.store))}
        wrong = ceremony[:-64] + 'a' * 64
        self.assertEqual(self.call('/api/passkey/login/verify', body, [wrong])['statusCode'], 400)
        self.assertEqual(self.call('/api/passkey/login/verify', body, [ceremony])['statusCode'], 200)
        options, ceremony = self.prepare('register')
        self.call('/api/logout', cookies=[self.password_cookie, ceremony])
        result = self.call('/api/passkey/register/verify', {'challenge_id': options['challenge_id'],
                           'credential': Authenticator().response(options, kind='register'), 'label': 'test'},
                           [self.password_cookie, ceremony])
        self.assertEqual(result['statusCode'], 401)

    def test_operator_recovery_and_rollback_clear_only_passkey_sessions(self):
        import importlib.util
        from pathlib import Path
        spec = importlib.util.spec_from_file_location('passkey_admin', Path(__file__).resolve().parents[1] / 'source/scripts/passkey-admin.py')
        admin = importlib.util.module_from_spec(spec); spec.loader.exec_module(admin)
        authenticator = self.register()
        cookie = self.login(authenticator)['cookies'][0].split(';')[0]
        key = passkeys.credential_key(authenticator.id)
        with patch.object(admin, 'Store', return_value=self.store), patch('sys.argv', ['operator', 'revoke', key]):
            admin.main()
        self.assertEqual(self.call('/api/session', cookies=[cookie], method='GET')['statusCode'], 401)
        # Previous backend has no credential-revocation check; cleanup removes its potential Session.
        with patch.object(admin, 'Store', return_value=self.store), patch('sys.argv', ['operator', 'clear-sessions']):
            admin.main()
        self.assertIsNone(self.store.get('AUTH#SESSION', web.token_from({'cookies': [cookie]})))
        self.assertIsNotNone(self.store.get('AUTH#SESSION', web.token_from({'cookies': [self.password_cookie]})))
