import type { Reading } from "./types";
import { FLOW_NEUTRAL_THRESHOLD_KW } from "./config";

export type FlowDirection = "forward" | "reverse" | "neutral" | "unknown";

export interface DirectionalFlow {
  direction: FlowDirection;
  powerKw: number | null;
  timestamp: number | null;
}

function finite(value: unknown) {
  if (value == null || typeof value === "boolean") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? Math.max(0, parsed) : null;
}

export function latestTimestamp(...readings: Array<Reading | undefined>) {
  const timestamps = readings
    .map(reading => Number(reading?.t))
    .filter(timestamp => Number.isFinite(timestamp) && timestamp > 0);
  return timestamps.length ? Math.max(...timestamps) : null;
}

/**
 * Direction is derived from the already-normalised backend import/export or
 * charge/discharge channels. No signed frontend remapping is performed.
 */
export function directionalFlow(
  forward: Reading | undefined,
  reverse: Reading | undefined,
  thresholdKw = FLOW_NEUTRAL_THRESHOLD_KW
): DirectionalFlow {
  const forwardValue = finite(forward?.value);
  const reverseValue = finite(reverse?.value);
  const timestamp = latestTimestamp(forward, reverse);
  if (forwardValue === null && reverseValue === null) {
    return { direction: "unknown", powerKw: null, timestamp };
  }
  const forwardKw = forwardValue ?? 0;
  const reverseKw = reverseValue ?? 0;
  if (Math.max(forwardKw, reverseKw) < thresholdKw) {
    return { direction: "neutral", powerKw: 0, timestamp };
  }
  return forwardKw >= reverseKw
    ? { direction: "forward", powerKw: forwardKw, timestamp }
    : { direction: "reverse", powerKw: reverseKw, timestamp };
}

export function estimatedRemainingEnergyKwh(
  socPct: number | null | undefined,
  capacityKwh: number
) {
  if (socPct == null || typeof socPct === "boolean") return null;
  const soc = Number(socPct);
  if (!Number.isFinite(soc)) return null;
  return Math.max(0, Math.min(100, soc)) / 100 * capacityKwh;
}
