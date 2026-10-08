# Release Regression Checklist

每次 Release 必须逐项检查并记录 `PASS`、`FAIL` 或 `NOT TESTED`。`FAIL` 必须阻止 deployment；`NOT TESTED` 必须写明环境限制与 production smoke 方法。

| ID | Product behaviour | Required evidence | v0.6.2 |
| --- | --- | --- | --- |
| R01 | Current Readings 在 Today Day 约 5 秒刷新 | automated unit/source | PASS |
| R02 | Historical Day 仍刷新 Current Readings | automated unit/source | PASS |
| R03 | Current Week 仍刷新 Current Readings | automated unit/source | PASS |
| R04 | Historical Week 仍刷新 Current Readings | automated unit/source | PASS |
| R05 | Current Month 仍刷新 Current Readings | automated unit/source | PASS |
| R06 | Historical Month 仍刷新 Current Readings | automated unit/source | PASS |
| R07 | hidden tab 暂停 aggressive polling，visible 立即 catch-up | automated unit/source | PASS |
| R08 | PV current power / Generating state | DOM + unit | PASS |
| R09 | Home Load current power | DOM + unit | PASS |
| R10 | Battery Charging / Discharging / Idle 与 power | DOM + unit | PASS |
| R11 | Battery SOC thresholds 与 `≈` remaining kWh | DOM + unit | PASS |
| R12 | Grid Importing / Exporting / Neutral | DOM + unit | PASS |
| R13 | freshness 使用 per-reading source timestamp；age <=2m 不显示 TTL，>2m 才显示 | DOM + unit/source | PASS |
| R14 | Today 完整 local-day X-axis / future blank | automated unit/source | PASS |
| R15 | Week 完整 seven-day X-axis | automated unit/source | PASS |
| R16 | Month 完整 calendar-month X-axis | automated unit/source | PASS |
| R17 | Desktop Drag-select / reverse / tiny drag | unit + Browser | NOT TESTED |
| R18 | Desktop Wheel cursor-anchored X Zoom | unit + Browser | NOT TESTED |
| R19 | No Desktop Drag Pan | source + Browser | NOT TESTED |
| R20 | Drag-select 期间无 Tooltip/range label | source + Browser | NOT TESTED |
| R21 | Mobile horizontal 与 diagonal Drag-select lock | unit + device | NOT TESTED |
| R22 | Mobile vertical-dominant page scroll | unit + device | NOT TESTED |
| R23 | Mobile Tap point Tooltip | unit/source + device | NOT TESTED |
| R24 | Mobile Tap another point 更新 Tooltip | device | NOT TESTED |
| R25 | Tap visible Tooltip area 关闭 | source + device | NOT TESTED |
| R26 | No Mobile Pinch Zoom | source + device | NOT TESTED |
| R27 | No user Y-axis Zoom | source + Browser/device | NOT TESTED |
| R28 | Sync Zoom absolute-time state machine | automated unit | PASS |
| R29 | Global Restore 与 conditional toolbar | automated unit/source | PASS |
| R30 | Live update 不破坏 local Zoom | automated source guard | PASS |
| R31 | `<2026-10-01` legacy routing | backend unit | PASS |
| R32 | `>=2026-10-01` Fast routing / cross-source | backend unit | PASS |
| R33 | missing samples 不被制造；视觉 bridging 保留 | unit/source | PASS |
| R34 | Daily KPI 仍使用 FoxESS official report semantics | backend unit | PASS |
| R35 | History cache / revisit behaviour | Browser | NOT TESTED |
| R36 | Home Load Peak Day raw timestamp | backend unit | PASS |
| R37 | Home Load Peak Week/Month 使用 rollup max/max_ts | backend unit | PASS |
| R38 | Existing PV/Grid Peaks 保留 | backend unit + source | PASS |
| R39 | responsive 不隐藏 Card secondary information | visual desktop/mobile | NOT TESTED |
| R40 | session idle logout；polling 不延长 session | backend unit | PASS |
| R41 | deployment/rollback ZIP boundary 与 checksum | artifact audit | PASS |
| R42 | credentials/secrets 不进入 artifacts | secret scan | PASS |
| R43 | Password Login 后 landing 为 Overview / Day / Today | unit + Browser | NOT TESTED |
| R44 | Desktop/Mobile Tooltip interaction 不 dim/focus 其他 metrics | source + Browser/device | NOT TESTED |
| R45 | Chart metric visibility 使用 classic native checkbox | DOM + Browser/device | NOT TESTED |

当前 checklist：`45 total / 29 PASS / 0 FAIL / 16 NOT TESTED`。

`NOT TESTED` 原因：当前 build environment的 Playwright package存在，但 Chromium、Firefox、WebKit executable均缺失，且没有 real mobile device。相关 source/unit checks均通过，必须在 `DEPLOYMENT.md` 的 target-browser/device smoke中完成后才可 production release。

## Release gate

1. 读取四份 living specs。
2. 执行全部 automated tests 与 production build。
3. 按本表逐项归类。
4. 任何 FAIL：修复后重新执行相关项及相邻 regression。
5. Browser/device NOT TESTED 项必须进入 `TESTING.md` 与 deployment smoke，不得伪报 PASS。


## PR4 page lifecycle validation — 2026-10-08

以下是本次 frontend 变更的证据，不覆盖上表历史 release/device 状态。

| Check | Evidence | Result |
| --- | --- | --- |
| Period/request/session replacement 后的 success/error/401/finally 无 stale 写入 | deferred-promise page DOM tests | PASS |
| Daily completion-based 60s 续排、manual timer replacement、hidden/visible、logout/unmount | fake-timer page tests + mocked Chromium clock/visibility | PASS |
| Snapshot/live handoff：限定 range、多个 batch、live overlap、zero/null、cursor 单调、历史 latest 不写实时卡片 | page DOM + pure merge tests | PASS |
| Picker destroy 幂等、监听/close timer/scroll lock cleanup、无 detached focus、StrictMode rebuild | real shared.js DOM tests + mocked Chromium logout/login | PASS |
| PR3 chart regression：Desktop Hover/selection/Wheel、Sync/Restore、live zoom；mobile Tooltip/gesture 模拟 | 原有 Chromium mock browser smoke | PASS |
| 真实手机纵向滚动、Safari/iOS、实际 background-tab throttling、生产 API/deployment | 本环境未执行；在目标浏览器/设备及部署 smoke 复验 R07、R17–R27、R30、R43 与上述生命周期项 | NOT TESTED |

Browser 使用真实 headless Chromium，但 API、clock 与 visibility 可控模拟；mobile 使用合成 pointer events。不得据此标记真实设备或生产部署 PASS。
