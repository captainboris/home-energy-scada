# 变更记录

`CHANGELOG.md` 记录每个版本发生的改变；当前产品 contract 以 `PRODUCT_SPEC.md` 为准。

## Unreleased

### 重构

- 正式 React frontend 的 HTTP transport 从 `public/shared.js` 提取至 `src/api.ts`；保留请求选项、错误翻译、401 与取消契约。Session cancellation 仍由 `useSession` 管理，查询与 polling 调度仍在页面。

### 修正

- 明确 Password Login 后进入 Overview → Day → Today，不再继承上次停留的 Week/Month query 作为登录初始视图。
- Current Readings freshness age 继续使用每个 Reading fragment 的 source timestamp，并只在 age 超过 2 分钟时显示 TTL；age-based stale threshold 同步为 2 分钟。
- Historian 移除 `emphasis.focus=series`，Desktop Hover 与 Mobile Tooltip 不再 dim 其他 metrics 或改变 series 视觉权重。
- Metric visibility 从 ECharts line/dot swatch legend 改为经典 native checkbox controls。

### 保持

- Tooltip 本身、Drag-select、Wheel Zoom、Mobile Tap Tooltip、Sync Zoom / Restore、source routing、Fast Telemetry 与 Daily Analytics semantics 不变。
- Collector、Lightsail、DynamoDB schema、EventBridge 与 ingestion plane 不变。


## Repository bootstrap — 2026-10-02

- 新增 Git-ready source hygiene：`.gitignore`、LF-normalising `.gitattributes`、`VERSION` 与 component `RELEASE_MANIFEST.yaml`。
- 新增只读 CI gates：Backend/API、Collector、React/TypeScript build，以及 generated/private-file hygiene。
- 新增 clean-clone current-artifact builder；deployment/rollback ZIP继续作为 GitHub Release assets，不进入 Git history。
- 新增本地 Git/GitHub 初始化指南；application runtime behaviour与production resources均未改变。

## 0.6.2 — 2026-10-02

### 新增

- Current Readings 重组为 PV、Home Load、Battery、Grid 四个高密度 Energy Flow Card。
- Battery Card 同时显示 SOC、`≈` estimated kWh、Charging/Discharging/Idle 与 power；新增单点 `VITE_BATTERY_CAPACITY_KWH`（default 28）。
- Grid Card 显式显示 Importing/Exporting/Neutral；Home Load 显示 current household power。
- Energy Peaks 新增 Home Load Peak 与 winning sample timestamp；Fast Week/Month 使用 rollup `max/max_ts` metadata。
- 新增 `PRODUCT_SPEC.md`、`UI_BEHAVIOUR_SPEC.md`、`DATA_SEMANTICS.md`、`REGRESSION_CHECKLIST.md` 与 5 个 ADR。

### 修正

- Current Readings 5-second polling 不再依赖 Today Day；任何 Historian selected period 都保持 live，hidden tab 仍 pause，visible 即 catch-up。
- Current Readings 与 Historian live append分离：历史 Chart不接收 current points，current-containing period仍增量更新。
- `/api/history/live` 在 cursor 后无新 point 时仍返回 collector health 指向的最后 persisted reading；较新的 incremental row不会被滞后的 health item覆盖。
- Drag-select 删除 selection-time start/end label，并在 selection mode suppress ECharts Tooltip。
- Mobile gesture改为 generous horizontal cone + locked Pointer capture；移除 Chart surface `pinch-zoom`，保留 vertical page scroll。

### 保持

- v0.6.1 full-period X-axis、future blank、Desktop Wheel/Drag-select、Mobile Tap Tooltip、Sync Zoom、Global Restore 与 conditional toolbar。
- 2026-10-01 source boundary、visual gap bridging、official Daily Energy KPI、auth/session 与 caching semantics。
- Collector、Lightsail、EventBridge、DynamoDB schema/data 与 ingestion cadence不变。

### Deployment

- `home-energy-web-v0.6.2.zip`：Web/API latest + Peak analytics change。
- `home-energy-frontend-v0.6.2.zip`：React production static assets。
- Rollback baseline：v0.6.1 Frontend + production-equivalent v0.6.0 Web/API。

## 0.6.1 — 2026-10-01

### 修正

- Historian `baseRange` 改为完整 selected period，不再把 current Day/Week/Month 的 X-axis end 截到 `Date.now()`。
- Today、Current Week 与 Current Month 的未来部分保留为空白；不生成 future/synthetic records，也不将其计为 telemetry gap。
- Desktop Mouse Drag 恢复为 X-only Drag-select Zoom；关闭 Drag-to-Pan。
- Mobile 单指 horizontal-dominant gesture 恢复 Range Selection；vertical-dominant swipe 保持 page scroll；Chart two-finger Pinch disabled。
- Mobile Tap 只定位真实 non-null sample；支持 Tap another point 更新、Tap Tooltip 自身关闭。
- Sync Zoom / Restore 改为条件显示，并通过 `baseRange`、`localZoomRange`、`lastSyncedZoomRange` 实现完整 dirty state machine。
- Sync 继续使用 absolute timestamps；Global Restore 继续恢复全部 Charts 且不重置其他 UI state。

### 保持

- React + ECharts architecture、visual design、series visibility、Current Readings 与 Daily Analytics。
- `< 2026-10-01` legacy historian / `>= 2026-10-01` Fast Telemetry routing，以及 5s/1m/15m resolution policy。
- 约 5 秒 source-cursor incremental polling、hidden pause、live merge 与 zoom preservation。
- Collector、Lightsail、DynamoDB、EventBridge、backfill、Daily Summary 与 official-energy semantics。

### Deployment

- Frontend-only：`home-energy-frontend-v0.6.1.zip`。
- v0.6.0 Frontend artifact 作为 direct rollback baseline；没有 v0.6.1 Web/API 或 Collector artifact。

## 0.6.0 — 2026-10-01

### 新增

- React 19.1.1 + TypeScript 5.9.2 + Vite 7.1.7 multi-page static Frontend。
- Apache ECharts 6.0.0 Historian，包含 X-only `inside dataZoom`、desktop wheel、mobile pinch、pan、Tooltip、responsive resize 与 `sampling: "minmax"`。
- 每个 Chart 的“同步 Zoom”与“复原”按钮；absolute timestamp one-shot sync、post-sync independent zoom 与 global restore。
- `/api/history/unified`：以 `2026-10-01 Australia/Melbourne` 为 boundary，统一读取 legacy REST 与 Fast Telemetry history。
- `/api/history/live`：按真实 source cursor incremental Query，一次 response 更新 points、Current Readings 与 health。
- Hidden-tab pause、visible catch-up、overlap guard、freshness age 与 live-while-zoomed viewport preservation。
- Hashed static asset serving、gzip、immutable asset cache 与 live/HTML `no-store`。
- Backend/API、React state 与 static artifact tests；Playwright browser smoke source。

### 修改

- Day/Week/Month Fast Telemetry resolution 明确为 5s/1m/15m，并保持 server-side authoritative。
- Gap 绘制改为 `connectNulls: true`；storage 和 API 仍不制造 missing timestamps。
- Web/API visible version 更新为 0.6.0；REST core version 保留其真实 lineage 0.4.1。

### 保留

- FoxESS REST Collector、backfill、reconciliation、Scheduler、Daily Summary 与 official-energy semantics。
- Lightsail WebSocket Collector 与 `home-energy-telemetry` schema/data。
- v0.5.0 Vanilla Frontend source 和 known-good rollback artifacts。
- Existing auth/session、30 分钟 idle logout、i18n、calendar/date navigation 与 visual design。

### 没有发生

- 没有修改、部署、删除或重启任何 production resource。
- 没有生成 v0.6 Collector artifact。
- 没有 DynamoDB migration、fake September backfill、synthetic gap points 或 power-to-energy KPI integration。

### Known risks / TODO

- Target browsers 的 wheel-anchor、Safari/iOS pinch 与 visual regression 需要在真实设备完成 smoke；当前环境无法安装 Chromium。
- Overview/ECharts main chunk uncompressed 约 555 KiB；已 gzip/immutable cache，但未来可评估 route-level lazy split。
- Full viewport-aware LOD 未纳入 v0.6.0；absolute-time API/zoom boundary 已预留 extension point。
- 超长 15 分钟 range 应在 production 观察 Lambda duration、DynamoDB read units 与 response size。

## 0.5.0 — 2026-09-29

- 新增独立 Lightsail WebSocket Collector、5 秒 raw telemetry、1 分钟 rollup、health item 与 read-only Fast Telemetry API。
- 该版本作为 v0.6.0 的 ingestion baseline 与 rollback baseline 保留。
