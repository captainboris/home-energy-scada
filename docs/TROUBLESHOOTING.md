# Fast Telemetry 故障排查（v0.5 ingestion baseline）

v0.6.2 没有修改或重新部署 Lightsail Collector；本文只用于诊断已经运行的独立 ingestion service。Frontend/Web rollback 不需要停止该 service。

先运行：

```bash
sudo systemctl status home-energy-ws-collector --no-pager --full
sudo journalctl -u home-energy-ws-collector -n 200 --no-pager
sudo /opt/home-energy-ws-collector/current/healthcheck.sh
```

排查这项独立 service 时，不要修改或重启 production REST Collector。

## Service 无法启动

### `CONFIG_INVALID`

- 检查 `/etc/home-energy-ws-collector/environment` 中所有 required values。
- `FOXESS_PASSWORD_MD5` 必须正好是 32 个小写十六进制字符。
- `FOXESS_PASSWORD_MD5` 与 `FOXESS_PASSWORD` 只能设置一个。
- 确认 table、Region、site ID 与 WASM path。

### `ExecStartPre` 失败或 WASM 无法读取

```bash
sudo -u home-energy-ws test -r \
  /etc/home-energy-ws-collector/signature.wasm
namei -l /etc/home-energy-ws-collector/signature.wasm
```

目录预期 mode 为 `0750 root:home-energy-ws`；WASM 为 `0640 root:home-energy-ws`。重新运行 `install-signature-wasm.sh`，不要通过放宽整个 secret directory 权限来绕过问题。

### Python dependency error

确认 venv 存在并测试 imports：

```bash
/opt/home-energy-ws-collector/current/venv/bin/python -c \
  'import aiohttp,boto3,wasmtime; print("ok")'
```

如有需要，从准确的 v0.5.0 bundle 重新运行 `install.sh`。

## Authentication 与 protocol

### `FOXESS_AUTH_FAILED`

- 确认 email 属于 FoxESS web portal account。
- 用当前 portal password 重新计算 digest。
- 若 portal 本身不可用或要求额外 challenge，应等待恢复，不要加入 aggressive retry。
- Collector 不输出 token/password；不要启用 raw HTTP dump。

### `FOXESS_PROTOCOL_ERROR`

login 或 plant response 已不符合已验证结构。若 account 有多个 plants，明确设置 `FOXESS_PLANT_ID`；否则先取得新的脱敏 test capture 进行对比，再修改 parser/auth code。

### `WS_HANDSHAKE_401` / `WS_HANDSHAKE_403`

Service 会丢弃 cached token 并重新 authentication。若持续发生，检查 account access，并确认 FoxESS 是否更改了私有 socket protocol 或 Origin 要求。

### Signature/WASM failure

检查文件开头是 WebAssembly magic，而不是 HTML error page：

```bash
python3 - <<'PY'
from pathlib import Path
p=Path('/etc/home-energy-ws-collector/signature.wasm')
data=p.read_bytes()
print(len(data), data[:4] == b'\x00asm')
PY
```

不要盲目下载未固定版本的替代文件。先重新运行隔离 protocol test 并审查 upstream source。

## 已连接但没有 points

### State 在 `STALE` / `RECOVERING` 间切换

查看 health counters：

- `cached_frames` 增加：frame 的 `consumeTs=0`，拒绝它是正确行为。
- `stale_frames` 增加：`timeDiff` 超过配置 threshold，拒绝它是正确行为。
- `invalid_frames` 增加：payload shape/timestamp/unit 需要新的脱敏 capture 和 parser test。
- 完全没有 frames：检查 DNS、outbound 443、system clock 与 FoxESS service。

不要为了让 chart 看起来有数据而降低 freshness threshold，也不要用 receive time 合成 timestamp。

### Directional values 为 null

upstream direction code 未知，因此 parser fail closed。在受控测试中只检查 numeric code 和相邻的非敏感字段。只有对照已知现场行为确认物理方向后，才更新集中的 `GRID_*_CODE` 或 `BATTERY_*_CODE` 配置。

## DynamoDB write 失败

### Credential 不可读

```bash
sudo -u home-energy-ws test -r \
  /etc/home-energy-ws-collector/aws-credentials
namei -l /etc/home-energy-ws-collector/aws-credentials
```

### `AccessDeniedException`

确认 key 属于 add-on stack output 指定的 IAM user；table name/Region 正确；`SITE_ID` 与 stack parameter 一致。不要授予 administrator access；检查 policy 的 `dynamodb:LeadingKeys` condition。

### `ResourceNotFoundException`

table name 或 Region 错误，或者 add-on stack 尚未创建。这绝不是把 service 指向现有 history table 的理由。

### Queue overflow 或 write error

`WRITE_QUEUE_OVERFLOW` 表示有界 queue 拒绝 sample，避免无界 memory 增长。检查 AWS connectivity 与 throttling。后续成功 write 可恢复当前 health，但累计 counter 保留。调查 gap 前不要重置 counter 掩盖事件。

## API/frontend 仍使用 REST historian

1. 确认 Web Lambda role 已附加 add-on reader policy。
2. 在已登录状态调用 `/api/telemetry/health` 并记下 Request ID。
3. 检查 Web Lambda logs：
   - `TELEMETRY_NOT_CONFIGURED`；
   - `TELEMETRY_TABLE_NOT_FOUND`；
   - `TELEMETRY_ACCESS_DENIED`。
4. 确认当前为 Day/Week/Month；Quarter/Year/Other 本来就应使用 REST historian。
5. 确认 selected local-day partitions 中确实有 data。

Telemetry request 为空或失败时，已加载的 REST chart 会有意保留。若 collector stale 但存在历史 fast points，页面显示真实 points，并附 stale source indicator。

## API 返回 401

这是现有 dashboard session system，不是 FoxESS authentication。查看安全的 `error.code` 与 Request ID。常见 code 为 `SESSION_TOKEN_MISSING`、`TOKEN_INVALID`、`TOKEN_EXPIRED`、`SESSION_IDLE`。Web Lambda structured log 会记录 auth stage，但绝不记录 session token。idle/expired 后重新登录即可。

## 排查期间的安全回滚

将 Web frontend Layer 与 API code 换回已记录的 v0.4 artifacts，然后只停止 `home-energy-ws-collector`。新表保持不动；现有 Collector、Scheduler、history table、report 与 backfill 都无需更改。
