# v0.6.2 Testing Report

执行日期：2026-10-02。测试没有访问 Production AWS/FoxESS，也没有修改外部资源。

## Automated results

| Suite | Result | 重点覆盖 |
| --- | ---: | --- |
| Backend/API/history/static/source guards | 67 passed | auth、period、source routing、live latest、Home Load Peak、docs gate、artifact-facing source |
| Lightsail Collector regression | 23 passed | parser、writer、rollup、health、service；source byte-identical |
| React/Vitest/jsdom | 31 passed | Current Reading DOM、28 kWh、directions、polling policy、full range、gesture classifier、Zoom state |
| TypeScript + Vite production build | PASS | 617 modules transformed；multi-page dist |
| Deterministic release rebuild | PASS | Web与Frontend ZIP二次 build SHA-256 byte-identical |
| ZIP integrity/checksum/boundary | PASS | 2 deployment + 2 rollback artifacts；inner ZIP intact |
| Credential-pattern scan | PASS | source与所有 deployment/rollback ZIP未发现 private-key/AWS/OpenAI-key pattern |

## Targeted semantics

- Current Readings：Today/Historical Day/Week/Month共用 visible-session polling policy；historical history response不进入 cards。
- Energy Flow：Import/Export、Charge/Discharge/Idle/Neutral pure logic与 DOM fields通过；missing telemetry不伪装成 0。
- Battery：SOC 0/low/mid/high helper semantics沿用；72% × 28 kWh = 20.16 kWh，DOM显示 `≈ 20.2 kWh`。
- Gesture：near-horizontal、slight diagonal、moderate horizontal-cone与vertical-dominant classifier通过；selection mode不再包含 range label，CSS suppress Tooltip。
- Peaks：Fast Day raw sample、Week/Month rollup `max/max_ts`、API range integration与existing PV/Grid peak regression通过。
- Routing：September legacy、October Fast与cross-boundary tests通过；Daily official report tests通过。

## Regression Checklist

`REGRESSION_CHECKLIST.md`：42 total，29 PASS，0 FAIL，13 NOT TESTED。

13 项 `NOT TESTED` 都是必须由 rendered Browser或real mobile device验证的 interaction/visual项：Desktop actual Drag/Wheel/no-Pan/Tooltip suppression、Mobile actual Tap/diagonal lock/vertical scroll/dismissal/no-pinch、target-browser Y-axis behaviour、Browser cache/revisit与responsive visual layout。

环境有 Playwright package，但 Chromium、Firefox、WebKit executable均不存在，因此没有声称 Browser smoke通过。完整 smoke source保留在 `source/frontend-react/tests/browser-smoke.cjs`；部署前必须按 `DEPLOYMENT.md` 在 target browsers/devices执行。

## Reproduce

```bash
cd source/frontend-react
npm ci
npm test
npm run build
cd ../..
PYTHONPATH=source:source/lightsail-collector <venv-python> -m unittest discover -s tests -p 'test_*.py' -q
PYTHONPATH=source/lightsail-collector <venv-python> -m unittest discover -s source/lightsail-collector/tests -p 'test_*.py' -q
./source/scripts/build-current-artifacts.sh
cd artifacts/v0.6.2
sha256sum -c SHA256SUMS-v0.6.2.txt
```

Backend static-asset integration tests依赖先生成 `frontend-react/dist/`；CI已按此前后顺序执行。`build-current-artifacts.sh`只重建当前 Web/API与Frontend artifacts。历史 rollback binaries从对应 GitHub Release取得，不提交到repository。
