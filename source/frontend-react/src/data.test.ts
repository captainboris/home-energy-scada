import { describe, expect, it } from "vitest";
import { latestSeriesTimestamp, mergeLatest, mergePointSeries } from "./data";

describe("incremental historian merge", () => {
  it("deduplicates timestamps and keeps chronological order", () => {
    const result = mergePointSeries(
      [{ metric: "pv_power_kw", unit: "kW", points: [[20, 2], [10, 1]] }],
      [{ metric: "pv_power_kw", unit: "kW", points: [[20, 2.2], [30, 3]] }]
    );
    expect(result[0].points).toEqual([[10, 1], [20, 2.2], [30, 3]]);
    expect(latestSeriesTimestamp(result)).toBe(30);
  });

  it("advances a reading on source time even when its value is unchanged", () => {
    const result = mergeLatest(
      { load_power_kw: { t: 1000, value: 2.5 } },
      { load_power_kw: { t: 6000, value: 2.5 } }
    );
    expect(result.load_power_kw).toEqual({ t: 6000, value: 2.5 });
  });

  it("does not manufacture gap timestamps", () => {
    const result = mergePointSeries(
      [{ metric: "load_power_kw", unit: "kW", points: [[0, 1], [5000, 1.1]] }],
      [{ metric: "load_power_kw", unit: "kW", points: [[40000, 2]] }]
    );
    expect(result[0].points.map(point => point[0])).toEqual([0, 5000, 40000]);
  });
});
