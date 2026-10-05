import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

const labels: Record<string, string> = {
  "overview.current": "Current Readings",
  "overview.currentNote": "Realtime",
  "flow.pv": "PV",
  "flow.homeLoad": "Home Load",
  "flow.battery": "Battery",
  "flow.grid": "Grid",
  "flow.generating": "Generating",
  "flow.charging": "Charging",
  "flow.discharging": "Discharging",
  "flow.importing": "Importing",
  "flow.exporting": "Exporting",
  "flow.idle": "Idle",
  "flow.neutral": "Neutral",
  "flow.unavailable": "Waiting for telemetry",
  "flow.householdDemand": "Current total household demand",
  "flow.stale": "Stale",
  "flow.estimatedEnergyTitle": "Estimated from {capacity} kWh"
};

window.HomeEnergyUI = {
  ZONE: "Australia/Melbourne",
  IDLE_MS: 1800000,
  ACTIVITY_KEY: "activity",
  LOGOUT_KEY: "logout",
  SOC_THRESHOLDS: { criticalBelow: 30, lowBelow: 50, highAt: 80 },
  language: "en",
  t(key, variables = {}) {
    let value = labels[key] ?? key;
    for (const [name, replacement] of Object.entries(variables)) {
      value = value.replaceAll(`{${name}}`, String(replacement));
    }
    return value;
  },
  locale: () => "en-AU",
  setLanguage: () => undefined,
  writeStorage: () => undefined,
  socState(value) {
    const key = value < 30 ? "critical" : value < 50 ? "low" : value < 80 ? "normal" : "high";
    return { key, className: `soc-${key}`, label: key };
  },
  stampLabel: value => String(value ?? ""),
  analyticsTimeLabel: value => String(value ?? ""),
  localInput: () => ({ date: "2026-10-02", time: "00:00" }),
  todayString: () => "2026-10-02",
  displayDateTime: (date, time) => `${date} ${time}`,
  periodLabel: period => period.label,
  periodFromUrl: () => ({
    mode: "day", anchor: "2026-10-02", startMs: 0, endMs: 1,
    fromDate: "2026-10-02", fromTime: "00:00", toDate: "2026-10-03",
    toTime: "00:00", label: "Today"
  }),
  periodQuery: () => ({}),
  writePeriodUrl: () => undefined,
  PeriodNavigator: class { setCurrent() {} } as unknown as Window["HomeEnergyUI"]["PeriodNavigator"],
  api: async () => { throw new Error("API is not available in component unit tests"); }
};

afterEach(() => cleanup());
