# v0.6.2 Deployment Guide

## Changed deployment units

| Order | Artifact | Target | 内容 |
| ---: | --- | --- | --- |
| 1 | `artifacts/v0.6.2/home-energy-web-v0.6.2.zip` | existing `home-energy-web` Lambda function code | live latest decoupling + hybrid Peak analytics |
| 2 | `artifacts/v0.6.2/home-energy-frontend-v0.6.2.zip` | existing frontend Lambda Layer new version | React/Vite static assets |

不要部署、重启或修改 Collector、Lightsail、EventBridge/Scheduler、DynamoDB、IAM、Function URL、FoxESS credentials、backfill或 Daily Summary ingestion。

## Pre-deployment

1. 确认 Production Footer 为 v0.6.1，Web/API `/api/health` version为 0.6.0（v0.6.1未改 Web code）。
2. 记录当前 Web Lambda code version/alias与 attached v0.6.1 Frontend Layer ARN。
3. 确认当前 Lambda/Layer retained versions可用；若依赖 ZIP rollback，则从对应 GitHub Release下载并验证 checksum。
4. 确认 September legacy、October Fast、`/api/history/live` 与 official Daily Analytics健康。
5. 若 Production高于 v0.6.1，停止；基于真实更高版本重新评估。

## Deploy

1. 上传 `home-energy-web-v0.6.2.zip` 到 existing Web/API Lambda；保持 handler、role、environment、memory、timeout与 Function URL不变。
2. 验证 `/api/health` visible API version为 `0.6.2`，login、history与 summary endpoints返回正常。
3. 从 `home-energy-frontend-v0.6.2.zip` 创建 frontend Layer new version，建议 description `home-energy-frontend-v0.6.2-realtime-ux-spec`。
4. 只替换 `home-energy-web` attached frontend Layer ARN。
5. Hard refresh Overview/Daily；Footer应显示 v0.6.2。

ZIP root已经 deployment-ready；不要解开后重组。

## Mandatory smoke

1. 在 Today、Historical Day、Current/Historical Week、Current/Historical Month分别观察 Network：visible时 `/api/history/live`约 5 秒一次；cards保持 NOW。
2. hidden tab至少 15 秒：不 aggressive poll；返回时立即 request。
3. 检查 PV、Home Load、Battery SOC/`≈ kWh`/state/power、Grid direction/power与 source freshness。
4. Desktop：Hover Tooltip；开始 Drag后 Tooltip消失且只有 overlay；release Zoom；Wheel anchor；无 Pan/Y Zoom。
5. Mobile real device：Tap/second Tap/Tooltip dismissal；near-horizontal、slight diagonal、moderate horizontal-dominant selection；vertical-dominant page scroll；无 pinch Zoom。
6. Sync/Restore conditional state与 live-while-zoomed保持。
7. Energy Peaks Day/Week/Month包含 Home Load Peak与时间；Week/Month值不得退化为 display average。
8. September、October 1+、cross-boundary、future blank、gap bridging、Daily official Energy KPIs、language与responsive cards正常。

若 Web/API step失败，先回退 Web；若 Frontend smoke失败，按 `ROLLBACK.md`先回退 Frontend再回退 Web。

## Rebuild

```bash
cd source/frontend-react
npm ci
npm test
npm run build
cd ../..
./source/scripts/build-current-artifacts.sh
cd artifacts/v0.6.2
sha256sum -c SHA256SUMS-v0.6.2.txt
```

Rebuild不读取 Production credentials，也不调用 AWS/FoxESS。Full delivery bundle需要先从对应 GitHub Release取得 rollback binaries，再运行严格的 `build-v0.6.2-release.sh`。
