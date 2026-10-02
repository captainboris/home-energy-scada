# Data Semantics

版本基线：v0.6.2  
所有 calendar/date rendering：`Australia/Melbourne`

## Realtime power channels

| Canonical field | Unit | Meaning |
| --- | --- | --- |
| `pv_power_kw` | kW | 当前 PV generation power，非 Energy |
| `load_power_kw` | kW | 当前家庭总负载 power |
| `grid_import_power_kw` | kW | Backend 已确认的 Grid Import magnitude |
| `grid_export_power_kw` | kW | Backend 已确认的 Grid Export magnitude |
| `battery_charge_power_kw` | kW | Backend 已确认的 Battery charge magnitude |
| `battery_discharge_power_kw` | kW | Backend 已确认的 Battery discharge magnitude |
| `battery_soc_pct` | % | Battery SOC，范围 0–100 |

Import/export 与 charge/discharge 是独立 non-negative canonical channels。Frontend 不通过正负号重新猜方向；同一 entity 两个 channel 都近零时显示 Neutral/Idle。

## Battery estimated remaining energy

`estimated_kWh = clamp(SOC, 0, 100) / 100 × BATTERY_CAPACITY_KWH`

Nominal capacity 的唯一 Frontend 配置是 `VITE_BATTERY_CAPACITY_KWH`，默认 28。UI 必须显示 `≈`，不得称为 BMS measured remaining usable energy。v0.6.2 不建模 degradation、reserve、temperature derating 或 usable-capacity curve。

## Source routing

`FAST_TELEMETRY_START_DATE = 2026-10-01`，按 Melbourne local date 解释：

- boundary 之前：legacy REST Historian，典型 resolution ~5 minutes；
- boundary 当日 00:00 起：Fast Telemetry；
- cross-boundary：API 分段读取并按 absolute timestamp merge。

## Fast Telemetry

Raw item 约每 5 秒，保留真实 `source_epoch_ms`。One-minute rollup 每 metric 保存 `min/max/avg/last` 及 `min_ts/max_ts/last_ts`。Week/Month Chart 可聚合到 1m/15m display resolution，但 Peak analytics 使用 `max/max_ts`，不是 average。

## Legacy Historian

Legacy power sample 典型约 5 minutes。该 source 的 Peak 代表 legacy sampling 能观察到的最大值，不等同 5-second instantaneous peak。

## Daily Energy KPI authoritative source

以下 Energy totals 以 FoxESS official report/API 为 authoritative：PV Generation、Home Consumption、Grid Import、Grid Export、Battery Charge、Battery Discharge。Fast Telemetry power integration 不替代 official completed-day report。Fallback integration 只沿用既有受控逻辑，不改变 authoritative semantics。

## Peak definition

Peak 是 selected analytics range 内 canonical power channel 的最大真实观察值，并携带该 winning observation 的 timestamp：

- Fast <= 2 days：raw row value + `source_epoch_ms`；
- Fast Week/Month：rollup `max` + `max_ts`；
- Legacy：raw ~5-minute row value + stored local timestamp；
- Cross-source：比较各 segment candidate，返回较大者。

Home Load Peak 对应 `load_power_kw`。Browser 不从 downsampled Chart series 计算 Peak。

## Gap semantics

- Storage：missing sample absent；invalid sample 不强制写成 0。
- API：不生成 synthetic timestamps。
- Chart：`connectNulls` 只做 presentation bridging；不改变 storage truth。
- Future blank area：selected period 内尚未发生的时间没有 sample，保持空白。

## Freshness

`Updated Xs ago` 以 Reading 的 source timestamp 计算。HTTP request completion、Browser receive time 或 last poll time 都不是 freshness source。
