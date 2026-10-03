# Home Energy SCADA Product Fact Sheet

Version baseline: **v0.6.2**  
Product timezone: **Australia/Melbourne**

This is the short-form contract to read before modifying the project. It
summarises current product behaviour and architecture boundaries from the
living specifications. It is intentionally stricter and shorter than the full
specification set.

These facts are **protected defaults, not permanent prohibitions**. A task may
intentionally change one of them, but that change must be explicit. Unrelated
work must not silently alter them.

---

## 1. Architecture boundaries — CHANGE ONLY IF EXPLICITLY IN SCOPE

### Ingestion planes

- FoxESS REST -> existing Collector Lambda -> legacy historian + Daily Summary.
- FoxESS WebSocket -> Lightsail Collector -> Fast Telemetry raw + rollup.
- Web/API Lambda reads both historian planes and exposes one logical product
  view.
- Frontend never chooses DynamoDB tables and never performs source routing.

Unless explicitly requested, do **not** modify:

- `home-energy-collector` behaviour or cadence;
- Lightsail WebSocket Collector behaviour;
- EventBridge / Scheduler;
- DynamoDB schema or existing data;
- REST backfill / reconciliation;
- Fast Telemetry ingestion frequency;
- Daily Summary ingestion semantics;
- production IAM or infrastructure resources.

A Frontend or Web/API change is not permission to refactor ingestion.

---

## 2. Historian source routing — MUST PRESERVE

Boundary: **2026-10-01 00:00 Australia/Melbourne**

- before boundary: legacy REST historian, typically ~5-minute samples;
- from boundary: Fast Telemetry;
- cross-boundary range: server splits the request, reads both sources and
  merges by absolute timestamp;
- frontend does not select the source.

Display resolution policy:

- Day: raw ~5-second Fast Telemetry;
- Week: 1-minute rollup;
- Month: 15-minute rollup.

Missing samples remain missing. API/storage must not create synthetic points.
The chart may visually bridge real samples, but presentation must not invent
timestamps or values.

---

## 3. Current Readings layout — MUST PRESERVE UNLESS THE TASK IS A UI REDESIGN

Current Readings consists of exactly four primary compact energy-flow cards:

1. **PV**
2. **Home Load**
3. **Battery**
4. **Grid**

Responsive layout:

- desktop: 4-column compact grid;
- tablet / medium viewport: 2-column grid;
- narrow mobile: 1-column;
- responsive collapse must not hide the Battery state, Grid direction,
  estimated battery kWh or freshness information.

Card semantics:

### PV
- current PV power;
- Generating / Idle state;
- source freshness.

### Home Load
- current total household load power;
- source freshness.

### Battery
The same card shows:

- SOC %;
- `≈` estimated remaining kWh;
- Charging / Discharging / Idle;
- charge/discharge power when applicable;
- source freshness.

Nominal capacity comes from the single frontend config
`VITE_BATTERY_CAPACITY_KWH`, default **28 kWh**.

Estimated remaining kWh is presentation only:

`SOC / 100 × nominal capacity`

It is not BMS-measured usable energy.

SOC thresholds remain:

- <30%: critical;
- 30–49%: warning;
- 50–79%: normal;
- >=80%: healthy.

Flow state uses a small independent accent. Do not make the whole Battery card
change background colour for Charging / Discharging. Stale styling wins over
flow/SOC styling.

### Grid
- Importing / Exporting / Neutral;
- absolute power;
- source freshness.

Direction comes from backend-normalised import/export channels. Frontend must
not re-derive direction from signed values.

---

## 4. Current Readings realtime behaviour — MUST PRESERVE

While the user is authenticated and the page is visible:

- poll Fast Telemetry approximately every 5 seconds;
- Current Readings continues updating regardless of the selected Historian
  Day / Week / Month;
- source telemetry timestamp drives freshness;
- HTTP response time / browser receive time is not freshness.

When the tab is hidden:

- aggressive live polling pauses.

When visible again:

- perform an immediate catch-up;
- then resume the normal cadence.

Historical-period responses must not overwrite Current Readings with old
values.

Background polling must not extend the 30-minute idle session.

---

## 5. Historian time range and live append — MUST PRESERVE

- X-axis represents the full selected period.
- Future portions of Today / current Week / current Month remain blank.
- Do not truncate the selected range to observed data or `Date.now()`.
- Current Readings can remain live while viewing a historical period.
- Live points append to Historian only when the selected period contains the
  current time.
- Live updates must not reset a user's local zoom viewport.

---

## 6. Historian interaction contract — MUST PRESERVE

### Desktop

- Hover real point -> Tooltip.
- Horizontal Drag-select -> X-axis Zoom.
- Wheel inside plot -> cursor-anchored X-axis Zoom.
- Drag is selection, not pan.
- No user Y-axis Zoom.

### Mobile

- Tap a real point -> pinned Tooltip.
- Tap another real point -> update Tooltip.
- Tap visible Tooltip -> dismiss it.
- Horizontal or reasonable diagonal Drag -> Range Selection.
- Clearly vertical gesture -> normal page scroll.
- Once horizontal selection locks, small later vertical drift must not steal
  the gesture.
- No mobile pinch Chart Zoom.
- No user Y-axis Zoom.

During Drag-select:

- hide/suppress Tooltip;
- show selection overlay only;
- do not show temporary start/end/duration labels.

### Sync Zoom / Restore

- Sync uses absolute timestamps.
- Sync is a one-shot alignment; charts remain independently zoomable
  afterwards.
- Restore is global: all charts return to the full selected-period range.
- Toolbar visibility follows the existing zoom dirty-state model; do not keep
  Sync / Restore permanently visible to hide state bugs.

---

## 7. Data semantics — MUST PRESERVE

Canonical realtime channels are non-negative backend-normalised values:

- `pv_power_kw`
- `load_power_kw`
- `grid_import_power_kw`
- `grid_export_power_kw`
- `battery_charge_power_kw`
- `battery_discharge_power_kw`
- `battery_soc_pct`

Frontend must not reinterpret signed power to recover import/export or
charge/discharge direction.

Invalid/missing telemetry is unavailable, not zero.

---

## 8. Daily Energy — CHANGE ONLY IF EXPLICITLY IN SCOPE

Daily Energy totals for:

- PV Generation;
- Home Consumption;
- Grid Import;
- Grid Export;
- Battery Charge;
- Battery Discharge;

use the FoxESS official report/API as the authoritative source when available.

Do not replace this contract with numerical integration of 5-second power.
Existing controlled fallback behaviour may remain, but it must not be presented
as the authoritative source.

---

## 9. Energy Peaks — MUST PRESERVE

Peaks are calculated from source-preserving data, not from averaged chart
display points:

- legacy: observed ~5-minute raw sample;
- Fast range <= 2 days: raw ~5-second sample;
- longer Fast range: persisted one-minute rollup `max` + `max_ts`;
- cross-source: compare source candidates and return the winning value plus its
  timestamp/source metadata.

Home Load Peak uses `load_power_kw`.

Do not download an entire Month of 5-second data into the browser merely to
compute a peak.

---

## 10. Authentication / freshness — MUST PRESERVE

- Existing password-session model remains.
- Idle logout: 30 minutes of user inactivity.
- Background polling is not user activity.
- Source timestamp, not poll completion, determines reading freshness.
- Stale state has priority over ordinary energy-flow styling.

---

## 11. Change protocol

Before implementation, classify the task:

### A. Fact-preserving change
The requested work does not intentionally change this document.

Requirements:

- preserve every unrelated fact;
- add/adjust tests for the requested behaviour;
- do not modify this Fact Sheet merely because implementation details changed.

### B. Intentional Fact change
The request explicitly changes one or more facts above.

Requirements:

1. identify the exact Fact Sheet section being changed before editing;
2. explain the old vs new behaviour;
3. update this Fact Sheet;
4. update the corresponding living spec(s);
5. update tests;
6. update `docs/CHANGELOG.md`;
7. call out deployment / rollback consequences in the PR.

Silently changing a Fact is a regression even if all existing automated tests
still pass.

---

## Full specifications

This sheet does not replace:

- `docs/PRODUCT_SPEC.md`
- `docs/UI_BEHAVIOUR_SPEC.md`
- `docs/DATA_SEMANTICS.md`
- `docs/REGRESSION_CHECKLIST.md`
- `docs/ARCHITECTURE.md`

When detail differs or is missing here, inspect the relevant full
specification before changing code.
