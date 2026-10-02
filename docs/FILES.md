# v0.6.2 文件清单

## Primary implementation

| File | 作用 |
| --- | --- |
| `source/frontend-react/src/config.ts` | Battery capacity、poll/stale/neutral单点配置 |
| `source/frontend-react/src/energyFlow.ts` | direction与estimated kWh pure semantics |
| `source/frontend-react/src/components/CurrentReadings.tsx` | 4-entity dense Energy Flow cards |
| `source/frontend-react/src/overview.tsx` | period-independent Current Readings polling；conditional Chart append |
| `source/frontend-react/src/components/HistorianChart.tsx` | Tooltip suppression与gesture lock |
| `source/frontend-react/src/zoom.ts` | Mobile intent classifier与v0.6.1 zoom helpers |
| `source/frontend-react/src/daily.tsx` | Home Load Peak card |
| `source/telemetry_storage.py` | live latest与raw/rollup peak metadata read |
| `source/lambda_function.py` | hybrid range Peak analytics；Web/API v0.6.2 |
| `source/analytics.py` | Daily Summary schema保留 Home Load Peak |

## Governance

`PRODUCT_SPEC.md`、`UI_BEHAVIOUR_SPEC.md`、`DATA_SEMANTICS.md`、`REGRESSION_CHECKLIST.md` 与 `docs/adr/` 是 source-controlled product baseline。

## Release artifacts (not tracked by Git)

| Path | Role |
| --- | --- |
| `home-energy-web-v0.6.2.zip` | changed Web/API deployment |
| `home-energy-frontend-v0.6.2.zip` | changed Frontend deployment |
| `home-energy-web-v0.6.0.zip` | v0.6.1 production Web baseline |
| `home-energy-frontend-v0.6.1.zip` | v0.6.1 Frontend baseline |
| `SHA256SUMS-v0.6.2.txt` | artifact integrity |

这些 immutable binaries属于 GitHub Release assets，不进入 Git history。Git source package不包含 `node_modules`、`dist`、`.venv`、`__pycache__`、credentials或 production data。
