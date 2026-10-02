# Fast Telemetry 运维手册（v0.5 ingestion baseline）

v0.6.2 没有修改或重新部署 Lightsail Collector；本文只用于维护已经运行的 ingestion plane，不属于 v0.6.2 deployment steps。

## 正常 health

在 Lightsail host 上运行：

```bash
sudo /opt/home-energy-ws-collector/current/healthcheck.sh
```

健康状态要求全部满足：

- systemd service 为 active；
- state 为 `LIVE` 且 `connected=true`；
- 最新 fresh server sample 不超过 90 秒；
- 最新 successful write 不超过 90 秒；
- persisted health flag 为 true。

已登录 dashboard session 可通过 `GET /api/telemetry/health` 查看同一 persisted item；endpoint 不会暴露 FoxESS/AWS credential。

## 常用 service 命令

```bash
sudo systemctl status home-energy-ws-collector --no-pager --full
sudo journalctl -u home-energy-ws-collector --since '30 minutes ago' --no-pager
sudo journalctl -u home-energy-ws-collector -f
sudo systemctl restart home-energy-ws-collector
```

restart 只适用于新 Lightsail service。绝不要用本手册重启或重新部署 production REST Collector Lambda。

## 结构化事件

每行 log 都是 JSON。主要 events：

| Event | 含义 |
| --- | --- |
| `ws_collector_start` | process/version/config identifier，不含 secret |
| `ws_auth_refreshed` | portal session 已刷新 |
| `ws_connected` / `ws_disconnected` | socket lifecycle |
| `ws_state_transition` | CONNECTING/RECOVERING/LIVE/STALE/STOPPING |
| `ws_recovery_probe` | 超过 stale threshold 后的低频 probe |
| `ws_reconnect_requested` | stale timeout 或计划内 480 秒 refresh |
| `ws_reconnect_backoff` | 有界 retry delay 与 attempt count |
| `ws_write_error` | raw/rollup write attempts 全部失败 |
| `ws_queue_overflow` | 有界 queue 拒绝 sample |
| `ws_health` | 周期 counter 与当前状态 |

`write_errors`、`queue_overflows`、reconnects 都是累计值。后续成功 write 后当前 health 可恢复，但 counter 保留供 incident analysis。

## 状态解释

- 计划内 session refresh 时短暂进入 `RECOVERING` 属正常。
- `STALE` 少于 90 秒表示 connection 尚在，但没有新的权威 source timestamp。
- `cached_frames` 持续增加而 `fresh_frames` 不增加，表示 FoxESS 有响应但没有发布新 source telemetry；排除 cached frame 是正确行为。
- `fresh_frames` 增加而 `writes` 不变，说明 write path 或 queue pressure 有问题。
- raw `TS#` key 在增加但 REST `last_success_at` 过旧，只需调查原 REST path；两条 collector 链路彼此独立。

## 每日检查

1. Health item 的 `last_source_epoch_ms` 持续推进。
2. 当天 raw partition 有近期且唯一的 `TS#` keys。
3. `ROLLUP#60#` keys 推进，sample count 合理；完整一分钟、5 秒 cadence 时通常最多 12 个。
4. `write_errors` 与 `queue_overflows` 不应持续增加。
5. 现有 REST Collector `last_success_at` 仍独立推进。

## Credential rotation

### AWS key

1. 在专用 IAM user 上创建第二个 access key。
2. 以 root-owned 临时文件替换 `/etc/home-energy-ws-collector/aws-credentials`，然后 atomic move 到目标路径。
3. 只重启新 service，验证 health/writes。
4. 先 deactivate 旧 key，观察无异常后再 delete。

### FoxESS credential

1. 在不保存 raw password 的前提下生成新 MD5 digest。
2. 更新 `/etc/home-energy-ws-collector/environment`。
3. 只重启 `home-energy-ws-collector`，验证 authentication。

不得记录或粘贴上述 credential。MD5 digest 必须按 password-equivalent secret 处理。

## 更新 service

使用新的 versioned release directory。上传前审查 source/diff 并运行 tests。`scripts/update.sh` 会安装上传的版本，并且只重启新 systemd unit。保留之前的 `/opt/home-energy-ws-collector/releases/*` 以便快速回滚；secret 始终位于 release 目录之外的 `/etc`。

## 数据修复

对 add-on 而言 raw telemetry 是权威数据，1 分钟 rollup 是 derived data。进程启动时会自动重建最近 10 分钟。若更早范围的 rollup 损坏，应停止并另外编写经过审查的 offline rebuild tool：只读 raw `TS#` items，只覆盖相应 `ROLLUP#60#` items。不要从 REST sample 补造 5 秒 points，也不要伪造 missing timestamps。

## Retention 与 backup

新表没有 TTL，删除 stack 时也会保留。请监控 storage growth 与 cost。v0.5.0 为保持初始 add-on 简洁，没有启用 point-in-time recovery；如以后认为当前区域成本可接受，可明确开启。现有 history table retention 不变。

## 建议的外部 alarm

v0.5.0 已持久化足够状态供以后报警，但没有新增另一套 AWS runtime。未来最小 monitor 可在 `last_source_epoch_ms` 或 `last_write_at` 5 分钟未推进时报警，并带 state、error code、queue depth 与 reconnect count。不要将 alarm 与 production REST Collector lifecycle 耦合。
