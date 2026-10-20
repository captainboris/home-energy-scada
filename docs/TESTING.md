# v0.6.2 Testing Report

## Aggregate Sankey MVP — 2026-10-20 (Australia/Sydney)

Baseline main `ab0373f`: 118 frontend tests, TypeScript/Vite build and existing mocked Chromium chart/page smoke PASS. No production AWS/FoxESS access or deployment.

| Command / evidence | Result |
| --- | --- |
| `npm --prefix source/frontend-react test` | PASS — 153 tests (35 new model/component checks); original Session, page lifecycle, KPI/Current Readings and Historian tests retained |
| `npm --prefix source/frontend-react run build` | PASS — TypeScript + Vite; existing >500kB chunk warning remains |
| `PYTHONPATH=source:source/lightsail-collector <venv-python> -m unittest discover -s tests -p 'test_*.py' -q` | PASS — 101 backend/API/auth/actual-artifact tests, with mocked external services |
| `PYTHONPATH=source:source/lightsail-collector:tests <venv-python> -m unittest test_web_artifact -q` | PASS — 3 actual ZIP/module/resource-closure checks; host-matching Web package is test-only |
| `PYTHONPATH=source/lightsail-collector <venv-python> -m unittest discover -s source/lightsail-collector/tests -p 'test_*.py' -q` | PASS — 23; local mock socket tests need local-network access in a sandbox |
| `node source/frontend-react/tests/browser-smoke.cjs` | PASS — same Chromium mock Overview/Historian and page lifecycle smoke as baseline |
| `node source/frontend-react/tests/energy-sankey-smoke.cjs` | PASS — rendered positive/negative R with one scale, zero links absent, subpixel fallback, missing/old graph cleanup, rapid periods, 320/390/900/1440px resize, language, hover/tap, Partial and emulated touch scroll |

Browser setup: run frontend preview at `127.0.0.1:4173`; provide externally installed Playwright via `NODE_PATH` and Chromium via `PLAYWRIGHT_BROWSERS_PATH` when necessary. Set `SCADA_SMOKE_OUTPUT` to an ignored/scratch directory for PNGs. No browser tooling was added as an application dependency.

The rendered test exposed ECharts 6's 1px minimum edge extent. Production code omits zero edges and switches subpixel-positive cases to separate bars with a common kWh scale; it never rescales official values or creates balancing flows. No physical-loss tolerance is introduced. Tiny bar style assertions allow CSS serialization precision only.

NOT TESTED: real iPhone Safari/Home Screen/touch/VoiceOver, production AWS/FoxESS/deployment, actual AC/DC metering boundaries, aligned hourly report completeness/cutoff and FoxESS 24-slot DST behaviour. Mock data proves UI/accounting behaviour, not production data quality. Manual smoke: compare all six labels with existing KPI values, test positive/negative R, zero/missing/Partial/install-crossing periods, switch language/period, tap ribbons and vertically scroll on the target iPhone.

Deployment is frontend Layer only; keep current Web/Collector code and data. Rebuild deployment artifacts normally (the host-matching Web test ZIP is not a production deployment package). Rollback restores the previous frontend Layer. No version bump or release.

执行日期：2026-10-02。测试没有访问 Production AWS/FoxESS，也没有修改外部资源。

## Passkey validation — 2026-10-15 (Australia/Sydney)

- Baseline main `69cc74a`: frontend 101 tests/build; authentication-containing backend suite 37 tests PASS.
- `npm --prefix source/frontend-react test`: 118 PASS (17 new serialization/UI/Session checks).
- `npm --prefix source/frontend-react run build`: TypeScript/Vite PASS; existing chunk-size warning.
- `PYTHONPATH=source:source/lightsail-collector python -m unittest discover -s tests -p 'test_*.py' -q`: 101 PASS: 86 existing + 15 real-crypto/moto contract/recovery cases, including actual ZIP closure/negative controls.
- Pinned Web runtime dependency audit (`pip-audit -r source/requirements-web.txt --no-deps --disable-pip`): PASS, no known vulnerabilities in the final closure. Earlier vulnerable compatibility pins were replaced and protocol/ZIP tests rerun.
- Collector suite: 23 PASS; code unchanged.
- `browser-smoke.cjs`: Chromium mocked chart, simulated touch and page lifecycle PASS.
- `passkey-smoke.cjs`: real Chromium WebAuthn with a virtual authenticator, mocked HTTP APIs:
  registration/assertion, login landing and valid-session deep link PASS. Actual serialized browser responses also verified by pinned Python WebAuthn library.
- Canonical builder: production ARM64 wheels/package PASS. Actual Web ZIP extracted into a separate directory;
  network-disabled public Lambda Python 3.12 ARM64 runtime via user-mode QEMU: import index/index.web,
  module origins and a real signature PASS. This proves package/runtime compatibility, not production deployment.
- Existing artifact tests: host-matching ZIP in a fresh isolated Python process, missing module and missing
  cryptography negative controls, frontend resource closure PASS. Production artifacts must be rebuilt with
  default `WEB_ARCH=aarch64` after the host-matching test build.
- NOT VERIFIED: real iPhone Safari / Face ID / Home Screen, physical device recovery, production URL/IAM,
  AWS/FoxESS and deployment. Full-delivery builder not run (historical rollback ZIPs absent); lists/syntax checked.

Browser tools are optional local tooling (as with existing smoke), not runtime dependencies. Run a Vite
preview on port 4173, with Playwright resolvable in NODE_PATH and its Chromium installed, then:

```bash
node source/frontend-react/tests/browser-smoke.cjs
node source/frontend-react/tests/passkey-smoke.cjs
```

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
