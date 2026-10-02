# v0.6.2 → v0.6.1 Rollback Guide

## Rollback boundary

v0.6.2改变 Frontend与 Web/API read/analytics code，但不改变 schema、data或 ingestion。Rollback不操作 Collector、Lightsail、EventBridge、DynamoDB、backfill、Daily Summary或 credentials。

## Recommended order

1. 将 attached frontend Layer恢复为部署前记录的 v0.6.1 Layer ARN。
2. 将 Web/API Lambda function code恢复为部署前 version/alias（v0.6.1 Production Web baseline）。
3. Hard refresh；Footer回到 v0.6.1，`/api/health` API version回到 0.6.0。
4. 验证 login、Current Readings、Historian、Daily Analytics、September/October routing与 telemetry持续写入。

## Without retained versions

1. 从对应 GitHub Release下载并校验 `home-energy-frontend-v0.6.1.zip`，创建 rollback Layer并 attach。
2. 下载并校验 `home-energy-web-v0.6.0.zip`，恢复 Web/API function code；这是 v0.6.1使用的 production-equivalent Web baseline。
3. 保持 handler、role、environment、memory、timeout与 Function URL不变。

## Consequences

- v0.6.2期间写入的 telemetry继续存在；没有 data migration需要逆转。
- Home Load Peak与 period-independent Current Readings会回到 v0.6.1 behaviour，这是预期 rollback结果。
- 不删除 v0.6.2 artifacts/logs；保留 Request ID、Network capture、device/browser与 gesture sequence用于 root-cause。
