import { describe, expect, it } from "vitest";
import type { HistoryData, LiveData } from "./types";
import { appendLiveHistory, latestSeriesTimestamp, mergeLatest, mergePointSeries } from "./data";

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


describe("snapshot/live source metadata", () => {
  const snapshot: HistoryData = {
    source: "unified", timezone: "Australia/Melbourne", resolution: "auto", resolution_seconds: 5,
    resolution_authority: "server", checked_at: "snapshot", series: [], latest: {}, source_segments: [],
    range: { preset: "day", start_date: "", end_date: "", start_at: "", end_at: "", start_ms: 0, end_ms: 100, key: "0/100" },
    source_boundary: { timezone: "Australia/Melbourne", fast_telemetry_start_date: "", epoch_ms: 0, before: "", from_boundary: "" }
  };
  const packet: LiveData = {
    source: "ws_fast", timezone: "Australia/Melbourne", resolution: "5s", resolution_seconds: 5,
    since_ms: 0, through_ms: 200, sample_count: 1, health: {healthy: false}, checked_at: "live",
    points: [{metric: "pv_power_kw", unit: "kW", points: [[0, 0], [50, null], [100, 99]]}],
    latest: {pv_power_kw: {t: 50, value: null}, load_power_kw: {t: 200, value: 99}}
  };
  it("bounds historian metadata by real in-range source time, independent of the read cursor", () => {
    const before = JSON.stringify([snapshot, packet]);
    const merged = appendLiveHistory(snapshot, packet);
    expect(merged.series[0].points).toEqual([[0, 0], [50, null]]);
    expect(merged.latest).toEqual({pv_power_kw: {t: 50, value: null}});
    expect(merged.last_source_timestamp).toBe(50);
    expect(merged.latest_observed_at).toBe(new Date(50).toISOString());
    expect(merged.telemetry_health).toEqual({healthy: false});
    expect(merged.checked_at).toBe("live");
    expect(merged.range).toEqual(snapshot.range);
    expect(JSON.stringify([snapshot, packet])).toBe(before);
  });
  it("keeps source metadata monotone and treats epoch zero as a real timestamp", () => {
    expect(appendLiveHistory({...snapshot, last_source_timestamp: 80}, packet).last_source_timestamp).toBe(80);
    const zero = appendLiveHistory(snapshot, {...packet, points: [], latest: {pv_power_kw: {t: 0, value: 0}}});
    expect(zero.last_source_timestamp).toBe(0);
    expect(zero.latest_observed_at).toBe(new Date(0).toISOString());
  });
});
