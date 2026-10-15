"""Generate test-only credentials/assertions; production verification uses webauthn."""
import hashlib
import json
import secrets

import cbor2
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes
from webauthn.helpers import bytes_to_base64url as b64, base64url_to_bytes


class Authenticator:
    def __init__(self):
        self.private = ec.generate_private_key(ec.SECP256R1())
        self.id = secrets.token_bytes(32)
        numbers = self.private.public_key().public_numbers()
        self.public = cbor2.dumps({1: 2, 3: -7, -1: 1,
                                  -2: numbers.x.to_bytes(32, 'big'), -3: numbers.y.to_bytes(32, 'big')})

    def response(self, options, origin='https://energy.test', rp_id='energy.test', uv=True,
                 kind='login', user_handle=None, count=0, cross_origin=False):
        client = json.dumps({'type': 'webauthn.create' if kind == 'register' else 'webauthn.get',
                             'challenge': options['publicKey']['challenge'], 'origin': origin,
                             'crossOrigin': cross_origin}, separators=(',', ':')).encode()
        flags = 1 | (4 if uv else 0) | (64 if kind == 'register' else 0)
        auth = hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + count.to_bytes(4, 'big')
        if kind == 'register':
            auth += bytes(16) + len(self.id).to_bytes(2, 'big') + self.id + self.public
            response = {'clientDataJSON': b64(client), 'attestationObject': b64(cbor2.dumps(
                {'fmt': 'none', 'attStmt': {}, 'authData': auth}))}
        else:
            signature = self.private.sign(auth + hashlib.sha256(client).digest(), ec.ECDSA(hashes.SHA256()))
            response = {'clientDataJSON': b64(client), 'authenticatorData': b64(auth),
                        'signature': b64(signature), 'userHandle': user_handle}
        return {'id': b64(self.id), 'rawId': b64(self.id), 'type': 'public-key', 'response': response}
