# Home Energy SCADA v0.6.2 Final Report

## Outcome

- 最终版本：v0.6.2
- 基线：已部署 v0.6.1
- Release类型：UX refinement + Realtime enhancement + bug fixes + analytics + documentation governance
- Architecture migration：NO

## Current Readings

最终结构是4张 compact Card：

1. PV：current kW + Generating/Idle + source freshness；
2. Home Load：current total household kW + freshness；
3. Battery：SOC % + `≈ remaining kWh` + Charging/Discharging/Idle + power + freshness；
4. Grid：Importing/Exporting/Neutral + absolute power + freshness。

Battery capacity来自 `source/frontend-react/src/config.ts` 的单点 `VITE_BATTERY_CAPACITY_KWH`，default 28。Remaining energy使用 `SOC/100 × capacity`，明确显示 `≈`，不是BMS measured usable energy。SOC继续使用critical/warning/normal/healthy thresholds；flow status使用独立small accent，stale state优先且Card background不随charge/discharge大幅跳动。

Grid与Battery direction都消费Backend canonical split channels；Frontend没有重新翻转sign。Missing telemetry显示 unavailable，不伪造成0或Idle。

## 5-second polling bug

Root cause：v0.6.1 `shouldPollLive()`要求`period.mode === day`且now位于selected Day，因此Historical Day、Week、Month都不启动loop；selected history response的latest还可能先进入Current Readings。

Fix：central live loop现在只由authenticated session与page visibility控制。`latest`永远更新Current Readings；只有`periodIncludesTime(now)`时Historian消费incremental points。Period navigation不清空live cursor，historical response不写cards。hidden tab pause，visible immediate catch-up；Current Readings与selected Historian period完全decoupled。

Backend live response在cursor没有新point时，会读取collector health指向的最后persisted raw row作为latest；若health写入落后，较新的incremental rows优先。

## Chart interaction fixes

- Drag-select达到threshold后关闭既有Tooltip；selection期间event/CSS双重suppress ECharts Tooltip。
- Selection overlay不再显示start/end/duration text，因此没有selection-time Tooltip或layout pressure。
- Mobile intent classifier接受slightly/moderately diagonal horizontal gesture；锁定后setPointerCapture并阻止page scroll直到release/cancel。
- Vertical-dominant gesture不prevent default，page vertical scroll保留。
- Chart surface从`pan-y pinch-zoom`改为`pan-y`；ECharts native pinch/pan/Y zoom继续disabled。
- Desktop Hover、Mobile Tap pinned Tooltip、Tap another point、Tap visible Tooltip dismissal的source contract保留。

## Home Load Peak

Energy Peaks新增Home Load Peak，显示selected analytics range内`load_power_kw`最大值与真实winning sample timestamp。

- Fast Day：raw 5-second row + source timestamp。
- Fast Week/Month：existing one-minute rollup `max/max_ts`，不是averaged display point，也不下载完整Month raw dataset到Browser。
- Legacy：约5-minute raw sample；metadata明确source resolution。
- Cross-source：Web/API比较candidate并返回winner。

Existing PV/Grid Import/Grid Export peaks保留。Daily Energy KPI authoritative source没有改变，仍是FoxESS official report/API。

## Product specification baseline

新增：

- `docs/PRODUCT_SPEC.md`
- `docs/UI_BEHAVIOUR_SPEC.md`
- `docs/DATA_SEMANTICS.md`
- `docs/REGRESSION_CHECKLIST.md`
- `docs/adr/0001`–`0005`

Future Work被明确要求先读四份living specs、检查current source、按incremental change实施、报告conflict并逐项跑Regression Checklist。`CHANGELOG`只负责release history，不能替代Product Spec。

## Test / regression result

- Backend/API/history/static/source：67 passed。
- Lightsail Collector regression：23 passed。
- React/Vitest/jsdom：31 passed。
- TypeScript/Vite production build：PASS。
- deterministic deployment build、ZIP/checksum/boundary、credential-pattern scan：PASS。
- Regression Checklist：42 total / 29 PASS / 0 FAIL / 13 NOT TESTED。

13项NOT TESTED均是target Browser/real-device interaction/visual smoke；当前环境无可执行Chromium/Firefox/WebKit。Source/unit/DOM checks已通过，但production deployment前必须完成`DEPLOYMENT.md` smoke。

## Files changed

- Frontend：Current Readings、polling ownership、gesture/Tooltip、Energy Peaks UI、config/semantics helpers、CSS/i18n、tests、version/build output。
- Web/API：live latest read、Fast raw/rollup Peak analytics、Home Load Peak schema、API version。
- Docs/release：living specs、ADR、Architecture、Assessment、Testing、Deployment/Rollback、README、CHANGELOG、build/checksum artifacts。

## Production safety declaration

| Question | Answer |
| --- | --- |
| AWS resources modified during generation? | NO |
| Existing Collector modified? | NO |
| Lightsail modified? | NO |
| DynamoDB schema/data modified? | NO |
| EventBridge/Scheduler modified? | NO |
| Fast ingestion frequency modified? | NO |
| Daily Analytics Energy semantics changed? | NO |
| September legacy routing changed? | NO |
| October Fast routing changed? | NO |

Collector/Lightsail与infrastructure source已与v0.6.1做byte comparison（忽略test cache），保持identical。

## Deployment / rollback

Deployment order：先Web/API `home-energy-web-v0.6.2.zip`，验证health/API；再attach由`home-energy-frontend-v0.6.2.zip`创建的新Frontend Layer；最后target-browser/device smoke。

Rollback order：先恢复v0.6.1 Frontend Layer，再恢复v0.6.1 production-equivalent Web/API version；无既有version时使用`rollback/home-energy-frontend-v0.6.1.zip`与`rollback/home-energy-web-v0.6.0.zip`。不操作ingestion或data。

## Known limitations

- 当前环境无法执行rendered Browser/real mobile device smoke；13项已明确标为NOT TESTED。
- Overview/ECharts chunk约566 kB uncompressed，已gzip/immutable cache；本release没有引入route-level code split。
- Battery remaining kWh是nominal-capacity estimate，不包含degradation、reserve或temperature model。

## Master deliverable

`home-energy-scada-v0.6.2-realtime-ux-spec.zip`
