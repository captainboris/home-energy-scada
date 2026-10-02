# ADR-0001：React + TypeScript + Apache ECharts

- 状态：Accepted
- 日期：2026-10-01

## Context

Historian 需要 absolute-time axis、多个同步 Chart、Desktop/Mobile custom interactions 与可测试 state machine。Legacy imperative SVG 已难以安全演进。

## Decision

Frontend 使用 React + TypeScript；Historian renderer 使用 Apache ECharts。Application code 持有 period、visibility、zoom 与 Tooltip contract，ECharts 负责绘制。

## Consequences

Production 仍发布静态 assets；依赖锁定并通过 Vitest/TypeScript/Vite build。Native ECharts pan/pinch 被禁用，以免与 product contract 冲突。
