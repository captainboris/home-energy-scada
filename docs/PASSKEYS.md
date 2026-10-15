# Passkeys — controlled Web/API increment

Decision baseline: main `69cc74a`. The two preceding reviews are consolidated here:
reuse the existing Session; independent operator grants protect registration/management;
credentials survive password rotation; immediate credential revocation applies to subsequent
Passkey Session requests. No account/role framework, Cognito, new service, PWA migration,
ingestion change, or energy-schema change. No confirmed P0 design blocker remains;
production configuration and real-device verification are deployment gates.

## Contract and boundaries

- Password fallback stays available. Both explicit logins replace-navigate to Overview / Day /
  Melbourne Today; valid-session deep links remain intact.
- The same `__Host-energy_session`, DynamoDB Session, 30min idle and 7d absolute expiry apply.
  Polling never extends idle. Password rotation invalidates **old Sessions**, while approved
  Passkeys can obtain a new Session. Revoke credentials separately to remove their login ability.
- `userVerification=required` is enforced in the browser and server library; it permits Face ID,
  Touch ID or device passcode. Face ID is not a server-visible identity or device identifier.
- Revocation affects the credential and all synchronized copies. Passkey Sessions add one
  strong-consistent credential lookup per authenticated request, avoiding session-deletion races.
  Already-authorized in-flight requests are not undone. Password Sessions do not add this read.
- Single dashboard identity, persistent random user handle, multiple independently labeled keys.
  Duplicate/revoked IDs cannot be overwritten or resurrected by registration.
- Web-only `passkeys.py` uses pinned `webauthn`; no reverse Lambda import or crypto implementation.
  `storage.py` and all energy/Collector modules remain unchanged.

## Configuration (operator; no production changes made by this PR)

Default is disabled. Set `PASSKEY_ENABLED=true` and `PASSKEY_ORIGIN` to the exact browser HTTPS
origin, without path, trailing slash or port, e.g. `https://<url-id>.lambda-url.ap-southeast-2.on.aws`.
RP ID is that full hostname. The shared `lambda-url.ap-southeast-2.on.aws` suffix is not a valid
RP ID. Both HTTP Origin and signed client Origin must match configuration; no Host-derived or
wildcard allowlist. Ordinary code updates preserve the existing Function URL. Changing the
browser domain requires new registrations. Keep the existing URL, handler, role and frontend
Layer architecture. Verify the actual production hostname, Python 3.12 / arm64, and AUTH access
before enabling; the repository template is evidence, not a production inventory.

Authentication records use existing `AUTH#PASSKEY#<site>` keys: PROFILE, CRED#credential-ID-hash,
CHALLENGE#random-ID, GRANT#token-hash. Credential records have no TTL. Grants expire after
600s; challenges after at most 300s (registration also bounded by the grant expiry).
TTL is cleanup only; conditional operations explicitly enforce expiry. Grants/challenges
are consumed atomically across Lambda instances. Challenges bind purpose, origin, password
version, browser-only cookie nonce and, for registration, the issuing Session. Logout cancels
an outstanding browser challenge. There is one active ceremony cookie per browser context;
starting another ceremony replaces it. Cancelled registration needs a new operator grant.

Use separate register/manage grants. A manage grant can list while valid and authorizes
**one** revoke; it is not a general admin Session. No HTTP endpoint issues grants. Secrets
remain in component memory, never localStorage, query strings or logs. Store only grant hashes.
Existing IAM template permits AUTH keys; no table/GSI/IAM migration is proposed. Provisioned
capacity remains unchanged; extra auth traffic uses existing capacity. Public endpoints have
independent bounded IP/global rate limits; password thresholds remain unchanged.

## Operator and first iPhone registration

Use an existing authorized AWS CLI/SDK identity, with TABLE_NAME, SITE_ID and region configured.
Do not grant that AWS access to ordinary dashboard users. Install development dependencies locally.
The following commands are operational instructions, **not executed against AWS during development**:

```bash
python source/scripts/passkey-admin.py grant register --origin https://YOUR-EXACT-HOST
python source/scripts/passkey-admin.py list
python source/scripts/passkey-admin.py grant manage --origin https://YOUR-EXACT-HOST
python source/scripts/passkey-admin.py revoke CRED#HASH-FROM-LIST
```

1. After deployment/configuration and HTTPS checks, open the exact origin in iPhone Safari.
2. Sign in with the existing password. Expand **Passkey 管理 / Manage passkeys**.
3. Administrator privately supplies the freshly generated register grant (10 minutes); paste it
   into Administrator grant and enter a label. Do not put it in a URL or support log.
4. Click Prepare registration, then Continue verification. The second explicit gesture starts
   Safari's credential dialog. Save the Passkey using Face ID / device verification.
5. Log out. Click Sign in with a passkey, then Continue verification. Successful server verification
   uses the same Overview / Day / Melbourne Today landing as password login.
6. To add a second credential/provider, repeat with a new register grant. Synced copies of an
   existing credential do not need another registration.
7. Management list/revoke requires a manage grant. A grant remains usable for listing until expiry,
   then is consumed by one revoke. For a lost device, use password fallback and ask the operator
   to revoke that credential, then issue a fresh register grant. If a revoked entry remains in the credential provider, delete that entry before creating its replacement. Last-key revocation is allowed
   because the password remains the recovery path. Deleting a device copy alone is not server revocation.

Home Screen uses the same RP but has a separate storage context; Safari logout propagation via
localStorage is not promised across contexts. Server revocation/expiry still applies. No manifest,
service worker or offline cache is added. Real Safari/Home Screen/Face ID must be tested separately.

## API and packaging

Four POST ceremony routes: `/api/passkey/{login,register}/{options,verify}`. Options return
`{challenge_id, publicKey}`; verify accepts `{challenge_id, credential}` (registration adds label).
Login verify returns the unchanged Session payload/cookie; registration returns `{ok:true}`.
POST `/api/passkey/manage` accepts `{operation:list|revoke,permission,key?}` and requires a
valid Session plus scoped grant. Existing error envelope and Request ID remain; unknown/invalid
credentials use a generic failure. New bodies are bounded at 16KiB; old request limits unchanged.

Both active builders package `requirements-web.txt` plus `passkeys.py` only into Web ZIP.
Default `WEB_ARCH=aarch64`, Python 3.12 binary wheels; `WEB_ARCH=x86_64` is for matching local/CI
tests. Never deploy an x86 CI ZIP to arm64. No dependency Layer or runtime pip installation.

```bash
npm --prefix source/frontend-react test
npm --prefix source/frontend-react run build
PYTHONPATH=source:source/lightsail-collector python -m unittest discover -s tests -p 'test_*.py' -q
# Tests build a host-matching ZIP; rebuild production ARM64 afterward:
PYTHON=python WEB_ARCH=aarch64 bash source/scripts/build-current-artifacts.sh
```

## Deployment and rollback

Deploy Web ZIP first with Passkeys disabled, then the updated frontend Layer. Verify password
login and old sessions before configuring/enabling Passkeys and issuing any grants. Gate production
use on iPhone Safari and Home Screen real-device checks, recovery/revocation, URL and IAM validation.
No merge/deploy, version bump or release is performed by this change.

For a rollback that preserves revocation: disable Passkeys, wait for in-flight requests to drain
(at least the configured Lambda timeout), run the operator command below, then restore previous
Web ZIP and frontend Layer. Password Sessions remain. Keep the **current** APP_PASSWORD; restoring
an old password could reactivate old sessions. New AUTH records can remain inert.

```bash
python source/scripts/passkey-admin.py clear-sessions
```

The old handler does not enforce credential revocation on Passkey-tagged Sessions. Therefore
merely restoring its ZIP is insufficient for a security rollback. Rotating APP_PASSWORD instead
invalidates all Sessions, at the cost of logging every user out. Neither action deletes energy data.
