# 家庭能源 SCADA Product Specification

版本基线：v0.6.2  
产品时区：`Australia/Melbourne`

本文是当前 Production 应具备行为的 source of truth；它描述“系统现在应该是什么样”，不是 release history。历史变更记录见 `CHANGELOG.md`。

## 1. Overview

Overview 使用 React + TypeScript + Apache ECharts，提供四实体 Current Readings 与多图 Historian。Dark Theme、compact information density、desktop/mobile responsive layout 必须持续保留。

## 2. Current Readings

- 固定表达 PV、Home Load、Battery、Grid 四个 Energy Flow entities，不通过大量重复 Card 增加信息。
- 页面可见且 session active 时约每 5 秒读取 Fast Telemetry；selected Historian period 不得控制或停止这套更新。
- hidden tab 暂停 aggressive polling；重新可见时立即 catch-up，然后恢复约 5 秒 cadence。
- freshness / TTL 必须使用每个 Reading fragment 自己的 source telemetry timestamp；不得使用 Backend `checked_at`、response time 或 Browser poll time。
- 正常 fresh data 不显示“X 秒/分钟前更新”；只有 source age 超过 2 分钟才显示 TTL。age-based stale threshold 同为 2 分钟；`health.healthy === false` 仍可立即使用 stale styling，且 stale 状态优先于 flow colour。

### 2.1 PV

显示 current PV power（kW）及 `Generating`/`Idle` 状态。

### 2.2 Home Load

显示 current total household load power（kW）。

### 2.3 Battery

同一 Card 必须显示：

- SOC percentage；
- `≈` estimated remaining energy（kWh）；
- `Charging`、`Discharging` 或 `Idle`；
- charge/discharge power（非 Idle 时）；
- source freshness。

Nominal capacity 只有一个配置入口：Frontend build variable `VITE_BATTERY_CAPACITY_KWH`，默认 `28 kWh`。计算式为 `SOC / 100 × nominal capacity`；该值不是 BMS 实测 usable energy。

SOC colour thresholds 沿用：`<30% critical`、`30–49% warning`、`50–79% normal`、`>=80% healthy`。Charge/Discharge 使用独立 text/badge accent，不改变整张 Card 背景。

### 2.4 Grid

显示 `Importing`、`Exporting` 或 `Neutral` 及绝对 power。方向来自 Backend 已标准化的 import/export channels；Frontend 不反转 signed value。

## 3. Historian period semantics

- Day：完整 Melbourne local calendar day；DST day 可以是 23 或 25 小时。
- Week：Monday 00:00 到下一 Monday 00:00 的完整 seven-day range。
- Month：完整 calendar month。
- Quarter、Year、Other：API selected start inclusive、end exclusive。
- X-axis 永远使用完整 selected period；now 之后或没有 sample 的区间保持空白，不制造 synthetic samples。
- 历史数据缓存、visibility preference 与 existing revisit behaviour 保留；period change 不应影响 Current Readings live cursor。

## 4. History source routing

- local date `< 2026-10-01`：legacy REST ~5-minute Historian。
- local date `>= 2026-10-01`：Fast Telemetry。
- cross-boundary range：server 合并两段真实数据，严格按 boundary 路由。
- Day/Week/Month display resolution policy 分别为约 5s / 1m / 15m；rollup 保留 min/max/last envelope。

## 5. Live update separation

Current Readings 永远消费 `/api/history/live` 返回的 `latest`。只有 selected period 包含 current time 时，Historian 才消费 incremental `points`；完全 historical view 不追加 current points。Live update 必须保留每张 Chart 的 local zoom viewport。

History snapshot 返回时保留同一 period 加载期间已接受的真实 live 点；范围、重叠优先级与水位见 `DATA_SEMANTICS.md`。Period/session/request owner 失效或卸载后，旧请求的成功、失败与 finally 不得更新页面或触发登录；当前 session 的 401 仍进入现有登录处理。

## 6. Chart interaction

- Desktop：Hover Tooltip、horizontal Drag-select Zoom、cursor-anchored Wheel X-axis Zoom；无 Drag-to-Pan。Hover real point/series 不得改变其他 metrics 的 opacity，也不得产生 line-width/focus 强调效果。
- Mobile：Tap real point 固定 Tooltip；horizontal 或合理 diagonal Drag-select Zoom；明显 vertical gesture 继续 page scroll。
- Mobile 一旦锁定 Range Selection，直到 release/cancel 前都不得被 vertical drift 抢走。
- Drag-select 只显示 selection overlay，不显示 selection start/end/duration Tooltip。
- 禁止 Mobile Pinch Chart Zoom 与所有 user Y-axis Zoom；Mobile Tap/Tooltip 同样不得触发 series dimming/focus 视觉效果。
- 每个 Chart 的 metric visibility 使用经典 native checkbox controls；不使用 ECharts line/dot swatch legend 作为开关。
- 更详细 contract 见 `UI_BEHAVIOUR_SPEC.md`。

## 7. Sync Zoom 与 Restore

每张 Chart 持有 `baseRange`、`localZoomRange`、`lastSyncedZoomRange`。Full range 时隐藏 Sync/Restore；local zoom 后显示两者；Sync 后该 Chart 只显示 Restore；后续局部改变才重新显示 Sync。任一 Restore 是 global restore，所有 Chart 回到 selected period full range。

## 8. Gap rendering

Storage 与 API 保持 missing samples absent；Frontend 只连接真实 sample，允许视觉 bridging，但不得插值或生成虚假 timestamp/value。Future blank area 同样不得补点。

## 9. Daily Analytics

PV Generation、Home Consumption、Grid Import、Grid Export、Battery Charge、Battery Discharge 的 Energy totals 继续以 FoxESS official report/API 为 authoritative source。不得改成 5-second numerical integration；current-day official report 尚未产生时可显示 unavailable。

Daily 页面可见且 session active 时，summary 请求完成后约 60 秒继续刷新（成功或普通失败均续排），不并发、不重复安排 timer。手动刷新替换待执行 timer；hidden 时暂停新 polling，visible 时立即检查，已有请求未完成则合并为完成后一次检查。Period/session 切换或卸载结束旧 owner 的活动，不改变 summary 数据语义，也不把 polling 计为 human activity。

## 10. Energy Peaks

Energy Peaks 包含 PV、Home Load、Grid Import、Grid Export，scope 为 selected Day/Week/Month/Other range，并显示 winning sample timestamp。

- Legacy range：使用 legacy ~5-minute raw sample；不得声称为 5-second instantaneous peak。
- Fast range不超过两天：使用 raw 5-second sample。
- Fast Week/Month：使用 persisted one-minute rollup 的 `max` 与 `max_ts`，不得从 averaged display point 求 max，也不得把整月 5-second dataset 下载到 Browser。
- Cross-source range：比较各 source 的真实/保真 max candidate，返回较大者及其 timestamp/source metadata。

## 11. Authentication 与 session

访问使用现有 password session。明确完成 Password Login 后，初始 landing 必须是 Overview → Day → Today（URL replace 到当天 Day）；已有有效 session 的普通 deep-link/reload 不强制改写。30 分钟无用户 activity 自动 logout；background polling 不延长 idle session。Logout 不停止后台 ingestion。

## 12. Caching 与 responsive behaviour

保留现有 Historian cache/read policy，不因 Current Readings 独立 polling 清空 selected history。Desktop Current Readings 为 compact grid；中等 viewport 可 2-column；窄 Mobile 可 1-column，但 Battery state、Grid direction、estimated kWh 与 freshness 不得隐藏。

## 13. Future Work implementation rule

任何后续 Work 必须：

1. 先完整读取 `PRODUCT_SPEC.md`、`UI_BEHAVIOUR_SPEC.md`、`DATA_SEMANTICS.md`、`REGRESSION_CHECKLIST.md`；
2. 再检查 current source、tests 与真实 deployment artifacts；
3. 将新 requirement 视为 incremental change，不得 silent remove unrelated working behaviour；
4. 如果新 request 与本 Product Specification 冲突，先明确指出 conflict；
5. implementation 后同步更新 specs 与 `CHANGELOG.md`；
6. 逐项执行 Regression Checklist，并以 PASS / FAIL / NOT TESTED 报告。

`CHANGELOG.md` 记录“每个版本改变了什么”；本文件记录“当前系统应该是什么样”。两者不得互相替代。
