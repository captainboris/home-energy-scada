import type { Period } from "./types";

export function shouldPollCurrentReadings(hidden: boolean) {
  return !hidden;
}

export function periodIncludesTime(period: Period, timestampMs: number) {
  return period.startMs <= timestampMs && timestampMs < period.endMs;
}

export function shouldAppendToHistorian(period: Period, nowMs: number) {
  return periodIncludesTime(period, nowMs);
}

export function nextCursor(previous: number, through: number) {
  return Math.max(previous, through);
}
