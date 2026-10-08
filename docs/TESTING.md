# v0.6.2 Testing Report

执行日期：2026-10-02。测试没有访问 Production AWS/FoxESS，也没有修改外部资源。

## PR5 validation — 2026-10-08

基于 main `983bdb0`，仅提取 Web/API range orchestration；不改变事实表或 living behaviour specs。

| Check / command | Result |
| --- | --- |
| 原 Backend/API baseline | 67 PASS |
| 新 range contract tests，提取前后同一 fixtures | 14 PASS；12 个成功场景完整 range HTTP response 无差异；补 direct business/HTTP parity 和 25h DST 后为 16 PASS |
| 机械提取 AST 比较，其他 Lambda functions | PASS；只改 dependency/return boundary，daily/auth/bounds/HTTP/static bodies 未变 |
| `PYTHONPATH=source:source/lightsail-collector <venv-python> -m unittest discover -s tests -p 'test_*.py' -q` | 86 PASS：67 原有 + 16 range + 3 actual artifact checks |
| `PYTHONPATH=source/lightsail-collector <venv-python> -m unittest discover -s source/lightsail-collector/tests -p 'test_*.py' -q` | 23 PASS |
| frontend `npm test` / `npm run build` | 101 PASS / TypeScript + Vite PASS；source 未变，既有 chunk warning 保留 |
| canonical `build-current-artifacts.sh`（artifact test 实际调用）及最终 ZIP integrity/module boundary | PASS |
| 实际 Web ZIP 解压后独立 Python `-I`，只加入解压路径：`import index`、`index.web` health、应用 module origin | PASS；删除新增 module 的 negative control 必须 ModuleNotFoundError，PASS |
| Frontend ZIP 两份 HTML 与 Vite relative JS imports resource closure | PASS；不包含 Python code |
| artifact 目录执行 `sha256sum -c SHA256SUMS-v0.6.2.txt` | PASS |

测试复用 report/telemetry fixtures、fake stores、moto 与固定时钟，不调用真实 AWS/FoxESS。独立 ZIP worker 禁止 boto3 resource/client IO。当前/full-delivery builder 的 module list 同步，未重设计 packaging。

NOT TESTED：真实 AWS/FoxESS、browser/device 与 deployment；本次不改 frontend，不重复 browser interaction smoke。Full-delivery builder 未执行（需要历史 rollback ZIP）；canonical current artifacts 与两个脚本的 shell syntax 已验证。没有 merge/deploy、版本升级或创建 release。

部署只需更新 Web 后端代码，沿用当前 frontend Layer；回滚恢复前一个 Web deployment ZIP。

## PR4 validation — 2026-10-08

基于 main `27778d9`；原有 57 frontend tests/build/mock browser baseline 均通过。新增的首批 40 lifecycle/picker tests 在未修复 main 上为 30 FAIL / 10 PASS（再补充直接相关的 visibility/metadata checks），确认竞态及 cleanup 缺口。

- Frontend：最终 `npm test`（101 tests）PASS；`npm test -- --run src/data.test.ts src/pageLifecycle.test.tsx src/PeriodNavigator.test.tsx`（47 tests）PASS。
- `npm run build`：PASS，TypeScript + Vite；原有 >500 kB chunk warning 仍存在。
- `PYTHONPATH=source:source/lightsail-collector <venv-python> -m unittest discover -s tests -p 'test_*.py' -q`：67 PASS。
- `PYTHONPATH=source/lightsail-collector <venv-python> -m unittest discover -s source/lightsail-collector/tests -p 'test_*.py' -q`：23 PASS。
- 先在 frontend 目录执行 `npm run preview -- --host 127.0.0.1 --port 4173 --strictPort`，再从 repo root 执行 `PLAYWRIGHT_BROWSERS_PATH=<installed-browser-path> SCADA_SMOKE_OUTPUT=<scratch-output> node source/frontend-react/tests/browser-smoke.cjs`：PASS。复用原有 chart smoke，并调用 `page-lifecycle-smoke.cjs` 检查 rapid period switching、stale success/401、manual + recurring refresh、visibility 模拟、logout/login 和 picker rebuild。
- 真实设备滚动、Safari/iOS、实际 background-tab throttling、production API 与 deployment：NOT VERIFIED。未合并或部署。

本次 Regression Checklist 证据单列于 `REGRESSION_CHECKLIST.md` 的 PR4 部分；下列内容仍是原 release 报告。

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
