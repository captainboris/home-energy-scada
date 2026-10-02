# v0.6.2 Implementation Assessment

本 Assessment 在修改前基于真实 v0.6.1 source、tests、docs 与 artifacts 完成。

| 检查项 | v0.6.1 真实状态 | v0.6.2 action |
| --- | --- | --- |
| Current Readings | PV、Load、Grid Import、SOC 四张低密度 Card | 重组为 PV/Home Load/Battery/Grid；增加 direction、power、estimated kWh |
| Live polling ownership | `overview.tsx` effect + `shouldPollLive()` | 保留 central loop，移除 period gate |
| Bug root cause | `period.mode === day` 且 now 位于 selected Day | Current Readings仅由 page visibility/session控制 |
| Battery fields | charge、discharge、SOC canonical fields已存在 | Frontend组合 state；不改 sign mapping |
| Grid fields | import/export canonical fields已存在 | explicit Importing/Exporting/Neutral |
| Home Load | `load_power_kw` 已存在 | 进入 Current Readings主 Card |
| Battery capacity | 无 centralized config | 新增 `VITE_BATTERY_CAPACITY_KWH`，default 28 |
| Peaks | PV/Grid Import/Grid Export | 增加 Home Load并保留 existing metrics |
| Week/Month Peak source | legacy raw rows；Fast rollup metadata未接入 | Fast使用 `max/max_ts`，不从 average chart data计算 |
| Tooltip | Desktop ECharts hover；Mobile custom pinned Tap | selection期间双重 suppress，普通 Tooltip不变 |
| Drag selection | custom Pointer Events；overlay含 range label | overlay-only，删除 selection-time label |
| Mobile gesture | strict 1.2 dominance；`pan-y pinch-zoom` | generous horizontal cone、intent lock、`pan-y` only |
| Docs | release docs，无 living Product/UI/Data/Regression specs | 建立四份 source-of-truth docs与 ADR |
| Tests | Backend、routing、v0.6.1 zoom/toolbar/Tap | 新增 flow、polling、diagonal lock、latest、raw/rollup Peak tests |

## Files changed

- Frontend：`config.ts`、`energyFlow.ts`、Current Readings、Overview live loop、Historian interaction、Daily Peaks、types、CSS/i18n 与 tests。
- Web/API：`telemetry_storage.py`、`lambda_function.py`、`analytics.py`、visible API version。
- Release：v0.6.2 build script、checksums、README、中文 documentation、ADR、regression evidence。

## Production resources deliberately untouched

| Resource | Modified? |
| --- | --- |
| Existing REST Collector / `home-energy-collector` | NO |
| Lightsail WebSocket Collector | NO |
| EventBridge / Scheduler | NO |
| DynamoDB schema or data | NO |
| Fast Telemetry ingestion frequency | NO |
| REST backfill / Daily Summary ingestion | NO |
| FoxESS/AWS credentials | NO |
| Daily Energy KPI authoritative source | NO |

Implementation无需 destructive production operation，因此按 task instruction直接完成；实际 Production deployment 仍须按 `DEPLOYMENT.md` 执行 smoke。
