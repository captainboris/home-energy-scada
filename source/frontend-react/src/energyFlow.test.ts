import { describe, expect, it } from "vitest";
import { directionalFlow, estimatedRemainingEnergyKwh, latestTimestamp } from "./energyFlow";

describe("Current Readings energy-flow semantics", () => {
  it("uses backend-normalised import/export channels without sign guessing", () => {
    expect(directionalFlow(
      { t: 1000, value: 1.24 },
      { t: 1000, value: 0 }
    )).toEqual({ direction: "forward", powerKw: 1.24, timestamp: 1000 });
    expect(directionalFlow(
      { t: 2000, value: 0 },
      { t: 2000, value: 0.83 }
    )).toEqual({ direction: "reverse", powerKw: 0.83, timestamp: 2000 });
  });

  it("treats near-zero flow as neutral and keeps the real source timestamp", () => {
    expect(directionalFlow(
      { t: 3000, value: 0.004 },
      { t: 3500, value: 0.008 }
    )).toEqual({ direction: "neutral", powerKw: 0, timestamp: 3500 });
    expect(directionalFlow(undefined, undefined)).toEqual({
      direction: "unknown", powerKw: null, timestamp: null
    });
  });

  it("calculates estimated remaining energy from the centralized capacity", () => {
    expect(estimatedRemainingEnergyKwh(72, 28)).toBeCloseTo(20.16);
    expect(estimatedRemainingEnergyKwh(0, 28)).toBe(0);
    expect(estimatedRemainingEnergyKwh(100, 28)).toBe(28);
    expect(estimatedRemainingEnergyKwh(null, 28)).toBeNull();
  });

  it("uses telemetry timestamps rather than browser polling time", () => {
    expect(latestTimestamp({ t: 1000, value: 1 }, { t: 5000, value: 1 })).toBe(5000);
  });
});
