# Home Energy SCADA

Private monorepo source baseline for Home Energy SCADA v0.6.2.

This repository contains the React/ECharts frontend, Web/API Lambda source,
Lightsail WebSocket collector, infrastructure references, automated tests and
the product specification baseline. It does not contain credentials,
production telemetry, generated frontend assets or deployment/rollback ZIPs.

## Release status

- Product source: `0.6.2`
- Suggested initial Git tag: `v0.6.2-rc.1`
- Automated validation: Backend/API 67 passed, Collector 23 passed, React 31 passed
- Manual browser/device smoke: pending; see `docs/REGRESSION_CHECKLIST.md`
- Production resources changed while preparing this source package: no

Component versions and release state are recorded in
`RELEASE_MANIFEST.yaml`.

## Repository layout

- `source/frontend-react/` — React, TypeScript and Apache ECharts frontend.
- `source/lightsail-collector/` — FoxESS WebSocket collector service.
- `source/*.py` — Web/API Lambda, analytics and historian modules.
- `source/scripts/` — deterministic artifact builders.
- `infrastructure/` and `source/infrastructure*.yaml` — existing IaC references.
- `tests/` — Backend/API/history/source regression tests.
- `docs/` — product, UI and data specifications, ADRs and runbooks.

## First local setup

Git initialisation, first-push and Windows notes are in `docs/GIT_SETUP.md`.

### Frontend tests and build

```bash
cd source/frontend-react
npm ci
npm test
npm run build
cd ../..
```

The full Python suite includes static-asset integration tests, so build the
frontend first in a clean clone.

### Python tests

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt

PYTHONPATH=source:source/lightsail-collector \
  python -m unittest discover -s tests -p 'test_*.py' -q
PYTHONPATH=source/lightsail-collector \
  python -m unittest discover -s source/lightsail-collector/tests -p 'test_*.py' -q
```

### Build current deployment artifacts

After the frontend build:

```bash
./source/scripts/build-current-artifacts.sh
```

Generated ZIPs and checksums are written to `artifacts/v0.6.2/` and are
ignored by Git. Upload immutable binaries to a GitHub Release instead of
committing them to the repository.

## Change governance

Before modifying product behaviour, read:

1. `docs/PRODUCT_SPEC.md`
2. `docs/UI_BEHAVIOUR_SPEC.md`
3. `docs/DATA_SEMANTICS.md`
4. `docs/REGRESSION_CHECKLIST.md`

Future changes should be incremental, preserve truthful telemetry semantics
and must not silently modify production ingestion or Daily Energy semantics.
