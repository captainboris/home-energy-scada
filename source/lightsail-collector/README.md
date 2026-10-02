# 家庭能源持久 FoxESS telemetry collector v0.5.0

这是一个独立、长期运行的 Lightsail service。它补充现有 REST Collector Lambda，但不会替换、调用、配置该 Lambda，也不与它共享 runtime state。

## 接受哪些数据

Service 登录 FoxESS web portal，打开已验证的 `wsmaitian` WebSocket，发送一次初始 `getdata`，随后消费 server-originated frames。只有全部满足以下条件时，frame 才成为 historian point：

- frame 与 `result.node` 结构符合预期；
- `errno == 0`；
- `result.timeDiff` 为数字，且不超过 `FRESH_TIMEDIFF_MAX`，默认 30 秒；
- `result.consumeTs` 是合理、非零的毫秒 timestamp；
- 该 source timestamp 尚未接受。

Cached response（`consumeTs == 0`）、stale frame、malformed frame 与 duplicate source timestamp 会计入 health，但绝不写入 raw history。缺少的 interval 保持缺失，不会制造 interpolated sample。

## Process boundary

```text
FoxESS web portal/WebSocket
        ↓
parser + freshness gate + in-memory duplicate filter
        ↓
bounded asyncio queue
        ↓
DynamoDB conditional raw write + 1 分钟 rollup + health item
```

DynamoDB conditional raw write 是 durable duplicate authority；in-memory filter 只用于减少无谓 requests。Service 重启后，会从 raw points 重建最近 10 分钟的 1 分钟 rollups。

## Runtime state machine

- `CONNECTING`：正在 authentication 或打开 socket。
- `RECOVERING`：已连接但在等待 fresh server sample、reconnect，或处于 bounded backoff。
- `LIVE`：fresh samples 与 successful writes 均为 current。
- `STALE`：35 秒没有新 source timestamp；每 30 秒最多允许一次轻量 `getdata` recovery probe。
- 90 秒无 fresh sample 时 reconnect。
- 480 秒执行计划内 socket refresh。
- `STOPPING`：收到 SIGTERM/SIGINT；退出前 drain write queue。

Service 不会每 5 秒 polling。Initial request 与少量 stale-recovery probe 只是 control messages；只有通过 source-time gate 的 frames 才持久化。

## 文件

- `app/`：collector、parser、writer、health 与 protocol adapters。
- `systemd/home-energy-ws-collector.service`：hardened systemd unit。
- `scripts/install.sh`：安装 v0.5.0，默认不启动。
- `scripts/install-signature-wasm.sh`：安装本地 WASM，或从固定不可变 interoperability commit 下载。
- `scripts/healthcheck.sh`：检查 systemd 与 persisted DynamoDB health。
- `tests/`：离线测试与脱敏 frame fixture，不含 credential 或 production capture。

安装、部署、运维、测试与回滚请阅读总发布包的中文文档。不得把真实 credential 放入此目录或 ZIP。
