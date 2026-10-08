import { describe, expect, it, vi } from "vitest";
import { buildHistorianOptions } from "./components/historianOptions";
import type { SeriesRow } from "./types";

const hour = 3600000;
const fullRange = { from: 1000, to: 1000 + 24 * hour };
const points: SeriesRow["points"] = [[1000, 0], [2000, null], [5000, 1.234]];
const input = {
  id: "solar-load", unit: "kW", metrics: ["pv_power_kw", "load_power_kw"],
  series: [{ metric: "pv_power_kw", unit: "kW", points }], fullRange,
  zoom: { from: 10000, to: 50000 }, visibility: {}, hoverTooltipEnabled: true,
  metricLabel: (metric: string) => `label:${metric}`,
  formatTimestamp: (timestamp: number) => `stamp:${timestamp}`
};

describe("pure historian options", () => {
  it.each([23 * hour, 25 * hour, 7 * 24 * hour, 31 * 24 * hour])(
    "retains the entire %s ms period with partial/null data and an independent viewport", duration => {
      const range = { from: 1000, to: 1000 + duration };
      const option = buildHistorianOptions({ ...input, fullRange: range });
      expect(option.xAxis).toMatchObject({ min: range.from, max: range.to, type: "time" });
      expect(option.dataZoom[0]).toMatchObject({ startValue: input.zoom.from, endValue: input.zoom.to });
      expect(option.series[0].data).toBe(points);
      expect(points).toEqual([[1000, 0], [2000, null], [5000, 1.234]]);
      expect(option.series[0].connectNulls).toBe(true);
    }
  );

  it("uses only current visible series and explicit labels, without changing their appearance", () => {
    const option = buildHistorianOptions(input);
    expect(option.series[0]).toMatchObject({
      id: "pv_power_kw", name: "label:pv_power_kw", showSymbol: false,
      lineStyle: { width: 1.4, color: "#f5c451" }, itemStyle: { color: "#f5c451" },
      emphasis: { disabled: true }
    });
    expect(option.series[1].data).toEqual([]);
    const livePoints: SeriesRow["points"] = [...points, [6000, 2]];
    const updated = buildHistorianOptions({
      ...input, visibility: { load_power_kw: false }, metricLabel: () => "当前语言",
      series: [{ ...input.series[0], points: livePoints }, { metric: "load_power_kw", unit: "kW", points }]
    });
    expect(updated.series[0].data).toBe(livePoints);
    expect(updated.series[0].name).toBe("当前语言");
    expect(updated.series[1].data).toEqual([]);
    expect(updated.dataZoom).toEqual(option.dataZoom);
    expect(option.series[0].data).toBe(points);
  });

  it("formats real readings through the supplied timestamp formatter, skipping null but retaining zero", () => {
    const formatTimestamp = vi.fn(input.formatTimestamp);
    const option = buildHistorianOptions({ ...input, formatTimestamp });
    expect(option.tooltip.formatter([
      { data: [1000, 0], seriesName: "PV" },
      { data: [1000, null], seriesName: "Missing" },
      { data: [1000, 1.234], seriesName: "Load" }
    ])).toBe("stamp:1000<br>PV: 0.00 kW<br>Load: 1.23 kW");
    expect(formatTimestamp).toHaveBeenCalledWith(1000);
    expect(option.tooltip.formatter([{ data: [2000, null] }, {}])).toBe("");
    expect(option.tooltip.formatter([])).toBe("");
    const soc = buildHistorianOptions({ ...input, unit: "%" });
    expect(soc.tooltip.formatter({ data: [1000, 72.4], seriesName: "SOC" })).toBe("stamp:1000<br>SOC: 72 %");
    expect(soc.yAxis).toMatchObject({ min: 0, max: 100, scale: false });
  });

  it("keeps application-owned X-only zoom and confined Tooltip behaviour", () => {
    const desktop = buildHistorianOptions(input);
    expect(desktop.dataZoom).toHaveLength(1);
    expect(desktop.dataZoom[0]).toMatchObject({
      id: "inside-solar-load", xAxisIndex: 0, disabled: true,
      zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: false,
      preventDefaultMouseMove: false, filterMode: "filter"
    });
    expect(desktop.dataZoom[0]).not.toHaveProperty("yAxisIndex");
    expect(desktop.tooltip).toMatchObject({ trigger: "axis", triggerOn: "mousemove", confine: true, enterable: true });
    expect(desktop.yAxis).toMatchObject({ min: 0, scale: true });
    const mobile = buildHistorianOptions({ ...input, hoverTooltipEnabled: false });
    expect(mobile.tooltip.triggerOn).toBe("none");
  });
});
