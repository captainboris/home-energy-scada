## Scope

<!-- What is this PR intended to change? Keep the scope narrow. -->

## Fact Sheet impact

- [ ] I read `AGENTS.md` and `docs/PRODUCT_FACT_SHEET.md`.
- [ ] This is a Fact-preserving change; no protected product fact is intentionally changed.
- [ ] OR: this intentionally changes a Product Fact, and the affected section(s) are listed below.

Affected Fact Sheet section(s), if any:

<!-- e.g. "Section 3 - Current Readings layout" -->

Old behaviour -> new behaviour, if intentionally changed:

<!-- Leave as "N/A" for a Fact-preserving change. -->

## Protected architecture boundaries

Confirm each item or explain why it is intentionally in scope:

- [ ] REST Collector / `home-energy-collector` unchanged.
- [ ] Lightsail WebSocket Collector unchanged.
- [ ] EventBridge / Scheduler unchanged.
- [ ] DynamoDB schema/data unchanged.
- [ ] Fast Telemetry ingestion frequency unchanged.
- [ ] REST backfill / reconciliation unchanged.
- [ ] Daily Energy authoritative semantics unchanged.
- [ ] Production IAM / infrastructure unchanged.

## Product behaviour touched

Check everything this PR can affect:

- [ ] Current Readings card content/layout
- [ ] Current Readings ~5s polling / visibility behaviour
- [ ] Freshness / stale-state semantics
- [ ] Historian source routing / resolution
- [ ] Historian full-range / future blank behaviour
- [ ] Desktop chart interaction
- [ ] Mobile chart interaction
- [ ] Sync Zoom / Restore
- [ ] Daily Energy
- [ ] Energy Peaks
- [ ] Authentication / idle session
- [ ] None of the above

## Validation

- [ ] Repository hygiene / secret scan
- [ ] React tests
- [ ] TypeScript + Vite build
- [ ] Backend/API tests
- [ ] Lightsail Collector regression tests, if relevant
- [ ] `docs/REGRESSION_CHECKLIST.md` reviewed for affected behaviour
- [ ] Required browser/device smoke completed, or remaining items explicitly marked NOT TESTED

## Deployment / rollback

Deployment impact:

<!-- None, frontend only, Web/API, ingestion, infrastructure, etc. -->

Rollback path:

<!-- State the rollback target or why no special rollback is needed. -->

## Notes

<!-- Risks, screenshots, logs, intentional deviations, follow-up work. -->
