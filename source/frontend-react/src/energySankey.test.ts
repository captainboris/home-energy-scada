import { describe, expect, it } from "vitest";
import fixture from "../tests/fixtures/energy-summary.json";
import { buildEnergySankey, buildEnergySankeyOptions, ENERGY_PORTS } from "./energySankey";
import type { DailyData, Period } from "./types";

const period: Period = { mode: "day", anchor: "2026-10-02", startMs: fixture.data.range.start_ms,
  endMs: fixture.data.range.end_ms, fromDate: "2026-10-02", fromTime: "00:00", toDate: "2026-10-03", toTime: "00:00", label: "Oct 2" };
const body = () => structuredClone(fixture.data) as DailyData;
const model = (data = body(), selected = period, today = "2026-10-03") => buildEnergySankey(data, selected, today);

describe("official aggregate energy accounting", () => {
  it("preserves all six report values, side percentages and positive difference without attribution", () => {
    const data = body(); const before = structuredClone(data); const result = model(data);
    expect(result).toMatchObject({ mode: "sankey", sources: 20, destinations: 15, difference: 5, notices: [] });
    expect(result.ports.map(port => port.value)).toEqual([10, 5, 5, 8, 3, 4]);
    expect(result.ports.map(port => port.share)).toEqual([50, 25, 25, 8 / 15 * 100, 20, 4 / 15 * 100]);
    expect(data).toEqual(before);
    const options = buildEnergySankeyOptions(result, key => key, String, () => "tip");
    expect(options.series[0].links).toHaveLength(6);
    for (const link of options.series[0].links) {
      expect([link.source, link.target]).toContain("pool");
      expect(link.value).toBe(data.energy![link.metric]);
    }
  });
  it("keeps negative R and does not scale either side", () => {
    const data = body(); data.energy!.load_kwh = 18;
    expect(model(data)).toMatchObject({ sources: 20, destinations: 25, difference: -5, mode: "sankey" });
  });
  it("rounds arithmetic noise at the existing three-decimal API precision, not a physical tolerance", () => {
    const data = body(); for (const port of ENERGY_PORTS) data.energy![port.key] = 0;
    Object.assign(data.energy!, { pv_kwh: 0.1, grid_import_kwh: 0.2, load_kwh: 0.3 });
    expect(model(data).difference).toBe(0);
    Object.assign(data.energy!, { pv_kwh: 0.3, grid_import_kwh: 0, load_kwh: 0.1, grid_export_kwh: 0.2 });
    expect(Object.is(model(data).difference, -0)).toBe(false);
    Object.assign(data.energy!, { pv_kwh: 0.1, grid_import_kwh: 0.2, grid_export_kwh: 0 });
    data.energy!.load_kwh = 0.301; expect(model(data).difference).toBe(-0.001);
    expect(model(data).ports.find(port => port.key === "load_kwh")!.value).toBe(0.301);
  });
  it("retains genuine zeros, including an all-zero state without percentage division by zero", () => {
    const data = body(); for (const port of ENERGY_PORTS) data.energy![port.key] = 0;
    expect(model(data)).toMatchObject({ mode: "zero", sources: 0, destinations: 0, difference: 0 });
    expect(model(data).ports.every(port => port.value === 0 && port.share === null && port.status === "official")).toBe(true);
    data.energy!.pv_kwh = 0.001;
    expect(model(data)).toMatchObject({ mode: "sankey", difference: 0.001 });
    const options = buildEnergySankeyOptions(model(data), String, String, () => "");
    expect(options.series[0].links.map(link => link.value)).toEqual([0.001]);
  });
  it("falls back before ECharts can inflate a subpixel ribbon, without changing its energy", () => {
    const data = body(); data.energy!.pv_kwh = 0.001;
    expect(model(data)).toMatchObject({ mode: "proportions", difference: -4.999 });
    expect(model(data).ports[0].value).toBe(0.001);
  });
  it.each([null, undefined, NaN, Infinity, -1])("does not replace invalid/missing %s with zero", value => {
    const data = body(); data.energy!.pv_kwh = value as number | null;
    const result = model(data);
    expect(result.mode).toBe("unavailable"); expect(result.difference).toBeNull();
    expect(result.ports[0]).toMatchObject({ value: null, status: value === undefined ? "missing" : "unavailable" });
  });
  it("does not use historian coverage to accept or reject official totals", () => {
    const data = body(); expect(model(data).mode).toBe("sankey");
    data.data_quality = { raw_coverage_pct: 100 };
    data.energy!.pv_kwh = null; expect(model(data).mode).toBe("unavailable");
  });
  it.each(["raw_power_integration", "unavailable_missing_official_report", undefined])("rejects unverified source %s", source => {
    const data = body(); data.metric_sources!.energy!.pv_kwh = source as string;
    expect(model(data).ports[0].status).toBe("unverified"); expect(model(data).mode).toBe("unavailable");
  });
  it("degrades on official-report warnings, keeping a zero distinct from a missing value", () => {
    const data = body(); data.energy!.pv_kwh = 0; data.energy!.load_kwh = null;
    data.warning_codes = [{ code: "OFFICIAL_REPORT_MISSING", days: [period.fromDate], metrics: ["load_kwh"] }];
    const result = model(data); expect(result.notices).toContain("reports");
    expect(result.ports[0].value).toBe(0); expect(result.ports[3].value).toBeNull();
  });
  it("keeps unrelated peak/telemetry warnings visible without replacing official energy", () => {
    const data = body(); data.warning_codes = [{ code: "FAST_PEAKS_UNAVAILABLE" }];
    expect(model(data)).toMatchObject({ mode: "sankey", notices: ["warnings"] });
  });
  it("marks today partial; missing today's report in a larger range cannot look complete", () => {
    expect(model(body(), period, period.fromDate).notices).toEqual(["partial"]);
    const data = body(); data.report_dates!.expected_days = 2;
    for (const port of ENERGY_PORTS) data.report_dates!.expected_days_by_metric[port.key] = 2;
    expect(model(data, period, period.fromDate)).toMatchObject({ mode: "unavailable", notices: ["partial", "coverage"] });
  });
  it("does not compare installation-crossing periods, even if all day counts happen to match", () => {
    const data = body(); data.availability!.battery_install_date = "2026-10-03";
    expect(model(data).notices).toContain("installation"); expect(model(data).mode).toBe("unavailable");
    data.availability!.battery_applicable = false;
    data.metric_sources!.energy!.battery_charge_kwh = "not_applicable_before_battery_install";
    data.energy!.battery_charge_kwh = null;
    expect(model(data).ports[5].status).toBe("notApplicable");
  });
  it.each(["official", "expected"])("rejects unequal %s day coverage", field => {
    const data = body(); data.report_dates![field === "official" ? "official_days_by_metric" : "expected_days_by_metric"].pv_kwh = 0;
    expect(model(data).notices).toContain("coverage"); expect(model(data).difference).toBeNull();
  });
  it("requires scope metadata and rejects a payload belonging to another period", () => {
    const wrongDates = body(); wrongDates.report_dates!.end = period.toDate;
    expect(model(wrongDates).notices).toContain("metadata");
    const data = body(); delete data.report_dates; expect(model(data).mode).toBe("unavailable");
    expect(model(body(), { ...period, startMs: period.startMs - 1 })).toMatchObject({ mode: "loading", ports: [], reportStart: null });
    expect(buildEnergySankey(null, period, "2026-10-03").mode).toBe("loading");
  });
  it.each([
    ["week", "2026-10-05", "2026-10-12", "+11:00", "+11:00", 7],
    ["month", "2026-10-01", "2026-11-01", "+10:00", "+11:00", 31],
    ["year", "2026-01-01", "2027-01-01", "+11:00", "+11:00", 365]
  ] as const)("reuses %s totals without history integration", (mode, fromDate, toDate, startOffset, endOffset, days) => {
    const data = body(); const selected = { ...period, mode, fromDate, toDate,
      startMs: Date.parse(`${fromDate}T00:00:00${startOffset}`), endMs: Date.parse(`${toDate}T00:00:00${endOffset}`) };
    Object.assign(data.range!, { start_ms: selected.startMs, end_ms: selected.endMs });
    data.availability!.foxess_data_start_date = "2026-01-01"; data.availability!.battery_install_date = "2026-01-01";
    Object.assign(data.report_dates!, { start: fromDate, end: new Date(Date.parse(toDate) - 86400000).toISOString().slice(0, 10), expected_days: days, completed_expected_days: days, complete_summary_days: days });
    for (const port of ENERGY_PORTS) { data.report_dates!.official_days_by_metric[port.key] = days; data.report_dates!.expected_days_by_metric[port.key] = days; }
    expect(model(data, selected, toDate).mode).toBe("sankey");
  });
  it.each([
    ["2026-10-04", "2026-10-05", "2026-10-04T00:00:00+10:00", "2026-10-05T00:00:00+11:00", 23],
    ["2027-04-04", "2027-04-05", "2027-04-04T00:00:00+11:00", "2027-04-05T00:00:00+10:00", 25]
  ])("accepts %s calendar bounds without assuming a 24h day", (fromDate, toDate, start, end, hours) => {
    const selected = { ...period, fromDate, toDate, startMs: Date.parse(start), endMs: Date.parse(end) };
    const data = body(); Object.assign(data.range!, { start_ms: selected.startMs, end_ms: selected.endMs });
    data.report_dates!.start = fromDate; data.report_dates!.end = fromDate;
    expect(selected.endMs - selected.startMs).toBe(Number(hours) * 3600000);
    expect(model(data, selected, toDate).mode).toBe("sankey");
  });
  it("rejects intraday windows rather than relabelling daily totals as intraday energy", () => {
    expect(model(body(), { ...period, mode: "other", fromTime: "12:00" }).mode).toBe("unsupported");
    expect(model(body(), { ...period, mode: "other" }).mode).toBe("sankey");
  });
});
