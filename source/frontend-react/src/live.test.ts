import { describe, expect, it } from "vitest";
import type { Period } from "./types";
import { nextCursor, periodIncludesTime, shouldAppendToHistorian, shouldPollCurrentReadings } from "./live";

const period: Period = {
  mode: "day", anchor: "2026-10-01", startMs: 1000, endMs: 100000,
  fromDate: "2026-10-01", fromTime: "00:00", toDate: "2026-10-02", toTime: "00:00", label: "Today"
};

describe("visibility-aware live polling", () => {
  it("keeps Current Readings polling independent of the Historian period", () => {
    for (const mode of ["day", "week", "month", "other"] as const) {
      expect(shouldPollCurrentReadings(false)).toBe(true);
      expect({ ...period, mode }.mode).toBe(mode);
    }
    expect(shouldPollCurrentReadings(true)).toBe(false);
  });

  it("appends live points only when the selected period contains now", () => {
    expect(periodIncludesTime(period, 50000)).toBe(true);
    expect(shouldAppendToHistorian(period, 50000)).toBe(true);
    expect(shouldAppendToHistorian({ ...period, startMs: 100000, endMs: 200000 }, 50000)).toBe(false);
    expect(shouldAppendToHistorian({ ...period, mode: "week", startMs: 0, endMs: 200000 }, 50000)).toBe(true);
    expect(shouldAppendToHistorian({ ...period, mode: "month", startMs: 0, endMs: 200000 }, 50000)).toBe(true);
  });

  it("never moves the source cursor backwards", () => {
    expect(nextCursor(6000, 5000)).toBe(6000);
    expect(nextCursor(6000, 10000)).toBe(10000);
  });
});
