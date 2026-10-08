# Code Architecture — Source / Ownership Map

本文说明当前源码入口、责任归属与交付边界。入口、模块归属或打包路径变化时更新本页。

Runtime topology 见 [ARCHITECTURE](ARCHITECTURE.md)；受保护边界见
[PRODUCT_FACT_SHEET](PRODUCT_FACT_SHEET.md)。Behaviour contract 以
[PRODUCT_SPEC](PRODUCT_SPEC.md)、[UI_BEHAVIOUR_SPEC](UI_BEHAVIOUR_SPEC.md) 与
[DATA_SEMANTICS](DATA_SEMANTICS.md) 为准；验证要求见
[REGRESSION_CHECKLIST](REGRESSION_CHECKLIST.md) 与 [TESTING](TESTING.md)。
既有决策见 ADR：[React/ECharts](adr/0001-react-echarts-frontend.md)、
[historian source boundary](adr/0002-fast-telemetry-boundary.md)、
[browser incremental polling](adr/0004-browser-incremental-polling.md)。

## Frontend source 与 ownership

Canonical frontend source 是 [source/frontend-react/](../source/frontend-react/)，
包括 `src/`、`public/`、两份 HTML entry 与 build configuration。

| Source | 当前 ownership |
| --- | --- |
| [overview.tsx](../source/frontend-react/src/overview.tsx) | Overview composition、selected period/history 的请求有效性与 pending-live handoff、独立 realtime polling/cursor、metric visibility 与跨 chart sync/restore commands |
| [daily.tsx](../source/frontend-react/src/daily.tsx) | Daily Analytics composition、selected period、summary request 有效性、completion-based 约 60 秒刷新与 visibility/teardown |
| [useSession.ts](../source/frontend-react/src/useSession.ts) | Session phase、login/logout、human activity、idle 与跨标签通知；维护 request controllers 并在退出或卸载时取消请求 |
| [api.ts](../source/frontend-react/src/api.ts) | 正式 React frontend 的 JSON HTTP transport、request timeout 与 error metadata/localization；使用 session 提供的 controller 集合，不拥有 polling 或 session phase |
| [HistorianChart.tsx](../source/frontend-react/src/components/HistorianChart.tsx) / [historianOptions.ts](../source/frontend-react/src/components/historianOptions.ts) / [zoom.ts](../source/frontend-react/src/zoom.ts) | Component 持有 ECharts instance/lifecycle、gesture/tooltip/selection、local zoom、Sync dirty-state 与 toolbar coordination；`historianOptions.ts` 是纯 options builder，接收显式 label/time formatter，并持有共享 palette/grid；`zoom.ts` 提供 zoom/gesture 计算 helpers |
| [CurrentReadings.tsx](../source/frontend-react/src/components/CurrentReadings.tsx) / [energyFlow.ts](../source/frontend-react/src/energyFlow.ts) | Reading cards、freshness 展示与显示时钟；energy-flow presentation helpers |
| [data.ts](../source/frontend-react/src/data.ts) / [live.ts](../source/frontend-react/src/live.ts) / [config.ts](../source/frontend-react/src/config.ts) | Series/latest merge、限定 range 的 snapshot/live merge 与 age formatting；live policy helpers；frontend configuration/constants。Polling 调度仍在页面 |
| [types.ts](../source/frontend-react/src/types.ts) | Frontend 使用的 API response 与 UI state 类型；server response 由 Python Web/API code 构造 |

### Active compatibility code 与历史 frontend

- [public/shared.js](../source/frontend-react/public/shared.js) **仍是正式 frontend 的运行依赖**：提供 `window.HomeEnergyUI`，拥有 translations/language、date/period/URL helpers、storage helpers、SOC presentation 与 imperative period picker。`api.ts` 使用它的 `t`、`hasTranslation` 与当前 language，不复制 dictionary。
- [ui.ts](../source/frontend-react/src/ui.ts) 接入该 global 并提供 React language subscription；[global.d.ts](../source/frontend-react/src/global.d.ts) 描述它的 TypeScript 接口；[PeriodNavigator.tsx](../source/frontend-react/src/components/PeriodNavigator.tsx) 接入 imperative picker，并在卸载时调用其幂等 `destroy()` 清理自身监听、关闭动画 timer 与滚动锁。两份 HTML 在 React module 之前加载 `/shared.js`。`public/shared.css` 也是 active styling source。
- `source/` 根目录的 `index.html`、`app.js`、`daily.html`、`daily.js`、`shared.js`、`shared.css` 是旧 frontend implementation，仍供 source-root static fallback 与部分 backend compatibility tests 使用；canonical React build / artifact builder 不取这些文件。
- [legacy-frontend-v0.5.0/](../source/legacy-frontend-v0.5.0/) 是历史实现存档，不是 React entry 或 canonical build input。不要将它与 active `frontend-react/public/` 混为一谈。

## Web/API 与 ingestion ownership

| Source | 当前 ownership |
| --- | --- |
| [lambda_function.py](../source/lambda_function.py) | Web/API handler、dispatch、auth/session、request/response/logging、static serving、daily summary；range endpoint 只解析窗口/安装配置并封装 HTTP response |
| [range_analytics.py](../source/range_analytics.py) | Web/API 专属 range business orchestration：安装日期适用性、官方报告完整性、两源真实 peaks、warnings、coverage/battery 与业务 payload；接收 window、now、legacy store、安装日期及 lazy Fast store factory，不反向导入 Lambda |
| [history_service.py](../source/history_service.py) | Unified historian read model：source selection、resolution policy 与两段 response 合并 |
| [telemetry_storage.py](../source/telemetry_storage.py) | Web/API 的 Fast Telemetry read adapter、raw/rollup display data、live incremental reads、health 与 peaks；不负责 ingestion writes |
| [analytics.py](../source/analytics.py) / [common.py](../source/common.py) | REST Collector 与 Web/API 共用的 daily analytics/report helpers，以及 metric/unit definitions、timezone/time parsing、AppError 等基础代码 |
| [storage.py](../source/storage.py) | Legacy historian、Daily Summary、REST Collector state/lease/budget 与 auth/session 的 DynamoDB access |
| [collector.py](../source/collector.py) | REST Collector Lambda：FoxESS requests、采集/backfill/reconciliation 与 Daily Summary 写入 |
| [lightsail-collector/app/](../source/lightsail-collector/app/) | 独立 WebSocket ingestion implementation：service、auth/socket、parser/model、dedupe、raw/rollup writer 与 health；入口是 `app.main` |

现有依赖方向：frontend 经 Web/API 读取数据；Web/API 组合 historian read modules，
不导入 REST Collector 或 Lightsail `app`。`lambda_function.py` 调用
`range_analytics.py`；该模块使用既有 `analytics.py`、historian boundary 与
Fast read adapter，返回业务数据，`checked_at` 仍读取计算完成时的时钟。
安装日期解析仍供 daily/range 共用；range 专用 day-start/peak helpers 在新模块。
REST Collector 使用 `analytics.py`、
`common.py`、`storage.py`；这些共用模块不依赖 Web entrypoint 或 Fast Telemetry read adapter。
Frontend 的 transport 在 `src/api.ts`，页面的 scheduling 在 React code，
session-related request cancellation 在 `useSession.ts`。Transport 每次注册独立 controller，
使用其 signal（延续覆盖 `options.signal` 的行为），完成时清理自身 controller 与 timeout；
session 负责退出/卸载时取消整个集合，401 后的 session phase 由调用方决定。

## Entrypoints、build 与 artifact 边界

- React 是 multi-page build：[index.html](../source/frontend-react/index.html) → `src/overview.tsx`；[daily.html](../source/frontend-react/daily.html) → `src/daily.tsx`。
- 在 `source/frontend-react/` 执行 `npm run build`，经 [package.json](../source/frontend-react/package.json) 的 TypeScript/build steps 与 [vite.config.ts](../source/frontend-react/vite.config.ts) 生成 `dist/`：两份 HTML、从 `public/` 复制的 shared assets、hashed `assets/`。`dist/` 是 generated output，不提交 Git。
- Web deployment handler 是 `index.web`。Canonical builder 将 [web_index.py](../source/web_index.py) 复制为 ZIP root 的 `index.py`，其 `web()` 调用 `lambda_function.lambda_handler`。[source/index.py](../source/index.py) 同时保留 `web` / `collect` wrappers；它不是 canonical Web ZIP 的 `index.py` 来源。
- Canonical current artifact builder 是 [build-current-artifacts.sh](../source/scripts/build-current-artifacts.sh)，输入已构建的 React `dist/` 和脚本中显式列出的 Web Python modules；它不执行 frontend build，也不部署。当前输出位于 `artifacts/v0.6.2/`。新 Web module 必须同步当前 builder（及 full-delivery builder）的显式 module list。

| Artifact | 内容 / 使用边界 |
| --- | --- |
| `home-energy-web-v0.6.2.zip` | Web/API Python modules 与上述 `index.py`；无 frontend static files、REST Collector 或 Lightsail code |
| `home-energy-frontend-v0.6.2.zip` | React `dist/` 内容直接位于 ZIP root；作为 frontend Lambda Layer，解压到 `/opt` |
| `SHA256SUMS-v0.6.2.txt` | 当前两份 ZIP 的 checksums；与 ZIP 一样是 generated output |

`lambda_function.frontend_file()` 逐文件按 configured `FRONTEND_ROOT`、`/opt`、
Python source root 查找资源；built frontend tests 使用 `FRONTEND_ROOT=dist`，
部分旧 static tests 使用 source-root fallback。Fallback 的存在不表示旧文件进入正式 React artifact。

[build-v0.6.2-release.sh](../source/scripts/build-v0.6.2-release.sh) 是包含 rollback
checksum 的完整交付工作流，依赖已取得的历史 ZIP；clean-clone current artifact rebuild
使用 canonical builder。部署与 rollback 步骤分别见 [DEPLOYMENT](DEPLOYMENT.md)、
[ROLLBACK](ROLLBACK.md)，源码交付清单见 [source/README](../source/README.md)。

## Validation locations

- Frontend unit/DOM tests：`source/frontend-react/src/*.test.ts(x)`；browser smoke：`source/frontend-react/tests/browser-smoke.cjs`。
- Backend/API/history/static tests：`tests/`；Lightsail tests：`source/lightsail-collector/tests/`。
- [CI](../.github/workflows/ci.yml) 执行 frontend tests/build 后运行 Python suites；built static/artifact tests 依赖先生成 `dist/`。`tests/test_web_artifact.py` 执行 canonical builder、检查最终 ZIP/资源闭包，并在独立 Python `-I` 进程仅加入解压 Web ZIP 路径验证 `index.web`；CI 的 Python suite 包含此检查。Browser smoke 不在 CI steps 中。
