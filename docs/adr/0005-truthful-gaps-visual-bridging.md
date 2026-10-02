# ADR-0005：Historian gap 保真、呈现可 bridging

- 状态：Accepted
- 日期：2026-10-01

## Context

Telemetry source 可能短暂缺失。填 0 或 synthetic interpolation 会改变 energy behaviour 与 Peak truth；完全断线又可能使长范围阅读困难。

## Decision

Storage/API 不制造 sample；missing/invalid 保持 absent/null。Frontend `connectNulls` 只在真实 endpoints 之间做视觉 bridging，Tooltip 与 analytics 仍只基于真实 sample。

## Consequences

未来空白区和真实 gap 不会生成虚假读数；visual line 不得被解释成 storage interpolation。
