# ADR-0004：Browser 使用 5-second incremental polling

- 状态：Accepted
- 日期：2026-10-02

## Context

Collector 已通过 WebSocket 写入 Fast Telemetry table。Browser 只需读取持久化状态；再建立第二套 Browser WebSocket 会增加 auth、fan-out、reconnect 与 production operations surface。

## Decision

Browser 在 visible + active session 下复用 `/api/history/live` 约每 5 秒 incremental poll。Response 同时提供 global `latest` 与 cursor 后的 `points`：Current Readings 始终消费 `latest`，只有包含 current time 的 Historian 消费 `points`。

## Consequences

hidden tab 暂停 aggressive polling，visible 时 immediate catch-up。Polling 不延长 idle session；不新增 Collector、EventBridge 或 WebSocket infrastructure。
