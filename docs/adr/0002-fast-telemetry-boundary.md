# ADR-0002：Fast Telemetry 从 2026-10-01 开始

- 状态：Accepted
- 日期：2026-10-01

## Context

Legacy REST Historian 已保存 September 与更早数据；新的 WebSocket Collector 从明确 cutover date 开始提供约 5 秒 telemetry。迁移或覆盖旧数据会提高风险。

## Decision

`FAST_TELEMETRY_START_DATE=2026-10-01`，按 `Australia/Melbourne` local midnight 切分。boundary 前读 legacy REST，boundary 起读 Fast Telemetry；cross-source range 在 Web/API read model 合并。

## Consequences

September 不会因新 source 消失；Fast table 与 legacy table schema/data 保持独立。任何 boundary change 都必须作为 architecture change 单独评审。
