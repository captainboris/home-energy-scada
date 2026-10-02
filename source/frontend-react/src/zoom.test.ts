import { describe, expect, it } from "vitest";
import {
  clampZoom,
  classifyTouchMovement,
  dragZoomRange,
  nearestRealPoint,
  restoreAll,
  selectedPeriodRange,
  syncAll,
  timeAtPixel,
  zoomAroundAnchor,
  zoomToolbarState
} from "./zoom";

describe("absolute zoom coordination", () => {
  const full = { from: 0, to: 86400000 };
  const selected = { from: 18 * 3600000, to: 20 * 3600000 };

  it("synchronizes absolute timestamps rather than percentages", () => {
    const charts = syncAll(["5s", "1m", "15m"], selected);
    expect(charts["5s"]).toEqual(selected);
    expect(charts["1m"]).toEqual(selected);
    expect(charts["15m"]).toEqual(selected);
  });

  it("allows a chart to diverge after a one-shot sync", () => {
    const charts = syncAll(["a", "b"], selected);
    charts.b = { from: 18.5 * 3600000, to: 19 * 3600000 };
    expect(charts.a).toEqual(selected);
    expect(charts.b).not.toEqual(charts.a);
  });

  it("restores every chart without touching unrelated state", () => {
    const restored = restoreAll(["a", "b", "c"], full);
    expect(Object.values(restored)).toEqual([full, full, full]);
  });

  it("clamps a cursor-anchored range to the selected period", () => {
    expect(clampZoom({ from: -10, to: 1000 }, full)).toEqual({ from: 0, to: 1000 });
  });
});

describe("full selected-period domain", () => {
  const period = { startMs: 100, endMs: 200 };

  it("uses the complete API range instead of the current data extent", () => {
    expect(selectedPeriodRange(period, { start_ms: 1000, end_ms: 9000 })).toEqual({ from: 1000, to: 9000 });
  });

  it("preserves Melbourne 23-hour and 25-hour local-day boundaries", () => {
    const hour = 3600000;
    expect(selectedPeriodRange({ startMs: 0, endMs: 23 * hour })).toEqual({ from: 0, to: 23 * hour });
    expect(selectedPeriodRange({ startMs: 0, endMs: 25 * hour })).toEqual({ from: 0, to: 25 * hour });
  });

  it("keeps full week and calendar-month endpoints even when data is partial", () => {
    const weekEnd = 7 * 86400000;
    const monthEnd = 31 * 86400000;
    expect(selectedPeriodRange({ startMs: 0, endMs: weekEnd })).toEqual({ from: 0, to: weekEnd });
    expect(selectedPeriodRange({ startMs: 0, endMs: monthEnd })).toEqual({ from: 0, to: monthEnd });
  });
});

describe("drag selection and wheel zoom", () => {
  const hour = 3600000;
  const day = { from: 0, to: 24 * hour };

  it("maps forward and reverse drags to the same absolute time range", () => {
    expect(dragZoomRange(750, 833.333333, 0, 1000, day, day, 8)).toEqual({
      from: 18 * hour,
      to: expect.closeTo(20 * hour, -1)
    });
    expect(dragZoomRange(833.333333, 750, 0, 1000, day, day, 8)).toEqual({
      from: 18 * hour,
      to: expect.closeTo(20 * hour, -1)
    });
  });

  it("ignores tiny accidental pointer movement", () => {
    expect(dragZoomRange(500, 505, 0, 1000, day, day, 8)).toBeNull();
  });

  it("selects a new range rather than panning an existing viewport", () => {
    const zoomed = { from: 18 * hour, to: 20 * hour };
    expect(dragZoomRange(250, 750, 0, 1000, zoomed, day, 8)).toEqual({
      from: 18.5 * hour,
      to: 19.5 * hour
    });
  });

  it("keeps cursor time anchored while wheel-zooming and clamps to the base range", () => {
    const anchor = timeAtPixel(750, 0, 1000, day);
    const zoomed = zoomAroundAnchor(day, anchor, 0.5, day);
    expect(zoomed).toEqual({ from: 9 * hour, to: 21 * hour });
    expect(zoomAroundAnchor(zoomed, anchor, 10, day)).toEqual(day);
  });
});

describe("toolbar state machine", () => {
  const base = { from: 0, to: 100000 };
  const first = { from: 10000, to: 50000 };
  const second = { from: 20000, to: 40000 };

  it("hides both actions at the full base viewport", () => {
    expect(zoomToolbarState(base, base, base)).toEqual({ isZoomed: false, showRestore: false, showSync: false });
  });

  it("shows Sync and Restore after a local zoom", () => {
    expect(zoomToolbarState(first, base, base)).toEqual({ isZoomed: true, showRestore: true, showSync: true });
  });

  it("hides Sync but keeps Restore after synchronization", () => {
    expect(zoomToolbarState(first, base, first)).toEqual({ isZoomed: true, showRestore: true, showSync: false });
  });

  it("shows Sync again only on the chart changed after synchronization", () => {
    expect(zoomToolbarState(second, base, first).showSync).toBe(true);
    expect(zoomToolbarState(first, base, first).showSync).toBe(false);
  });

  it("uses tolerance to absorb ECharts timestamp rounding", () => {
    expect(zoomToolbarState({ from: 500, to: 99500 }, base, base).isZoomed).toBe(false);
  });
});

describe("mobile real-point tooltip targeting", () => {
  const rows = [
    { metric: "pv", unit: "kW", points: [[1000, 1], [2000, null], [3000, 3]] as Array<[number, number | null]> },
    { metric: "load", unit: "kW", points: [[1100, 2], [3100, 4]] as Array<[number, number | null]> }
  ];

  it("targets a visible real sample and skips null or hidden series", () => {
    expect(nearestRealPoint(rows, ["pv", "load"], { pv: true, load: false }, 2100, { from: 0, to: 4000 }))
      .toEqual({ metric: "pv", pointIndex: 2, timestamp: 3000 });
    expect(nearestRealPoint(rows, ["pv", "load"], { pv: false, load: true }, 2100, { from: 0, to: 4000 }))
      .toEqual({ metric: "load", pointIndex: 0, timestamp: 1100 });
  });

  it("separates tap, horizontal selection, and vertical page scroll", () => {
    expect(classifyTouchMovement(5, 4)).toBe("pending");
    expect(classifyTouchMovement(40, 8)).toBe("horizontal");
    expect(classifyTouchMovement(8, 40)).toBe("vertical");
    expect(classifyTouchMovement(20, 19)).toBe("horizontal");
    expect(classifyTouchMovement(24, 27)).toBe("horizontal");
    expect(classifyTouchMovement(16, 30)).toBe("vertical");
  });

  it("keeps an intent decision stable for subsequent diagonal drift", () => {
    const initial = classifyTouchMovement(18, 12);
    expect(initial).toBe("horizontal");
    // HistorianChart stores the selected mode; later movement is not reclassified.
    expect(classifyTouchMovement(35, 26)).toBe("horizontal");
  });
});
