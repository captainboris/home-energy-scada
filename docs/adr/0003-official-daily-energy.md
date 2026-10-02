# ADR-0003：Daily Energy KPI 使用 FoxESS official report

- 状态：Accepted
- 日期：2026-10-01

## Context

Power samples 会有 cadence jitter、gap 与 source transition；直接数值积分会使 Daily Energy totals 与设备官方 counter/report 出现漂移。

## Decision

PV Generation、Home Consumption、Grid Import/Export、Battery Charge/Discharge 以 FoxESS official report/API 为 authoritative source。Fast Telemetry 用于实时 power、Historian、Peak 与 behaviour，不替代 completed-day official totals。

## Consequences

当前日报尚未产生或已结束日期缺失 official report 时明确显示 unavailable/warning，而不是静默用 5-second integration 冒充官方值。
