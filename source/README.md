# v0.6.2 Source Snapshot

## Deployable source

- Web/API：`lambda_function.py`、`history_service.py`、`telemetry_storage.py`、`analytics.py`、`common.py`、`storage.py`、`web_index.py`。
- Frontend source：`frontend-react/src/`、`public/`、build/test configuration。
- Frontend production output：由 `npm run build` 生成至 `frontend-react/dist/`，不提交 Git。
- Clean-clone artifact builder：`scripts/build-current-artifacts.sh`。
- Full delivery builder：`scripts/build-v0.6.2-release.sh`；需要从对应 GitHub Release 取得 rollback artifacts。

## Deployment archive boundaries

`build-current-artifacts.sh` 产生的 `home-energy-web-v0.6.2.zip` root只包含 Web/API Python modules；`index.py`来自 `web_index.py`。  
`home-energy-frontend-v0.6.2.zip` root只包含 `index.html`、`daily.html`、`shared.js`、`shared.css` 与 `assets/`。

不得加入 `node_modules`、tests、IaC、Collector、credentials、`.env` 或 rollback files。Collector/Lightsail/IaC source仅作为完整审计 snapshot保留，不属于 v0.6.2 deployment。

## Battery capacity

Frontend compile-time config `VITE_BATTERY_CAPACITY_KWH`可覆盖 nominal capacity；未配置时唯一 default为 28。Build artifact中的 estimated kWh semantics必须与 `docs/DATA_SEMANTICS.md`一致。

## Future changes

开始修改前先读四份 living specs；冲突时明确报告，不得 silent overwrite。完成后更新 specs/CHANGELOG并执行 Regression Checklist。
