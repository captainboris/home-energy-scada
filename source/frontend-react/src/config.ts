function positiveNumber(value: unknown, fallback: number) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

/**
 * Compile-time deployment configuration. Override with
 * VITE_BATTERY_CAPACITY_KWH when a different nominal battery is installed.
 */
export const BATTERY_CAPACITY_KWH = positiveNumber(
  import.meta.env.VITE_BATTERY_CAPACITY_KWH,
  28
);

export const FLOW_NEUTRAL_THRESHOLD_KW = 0.01;
export const REALTIME_POLL_INTERVAL_MS = 5000;
export const REALTIME_INITIAL_LOOKBACK_MS = 2 * 60 * 1000;
export const REALTIME_STALE_AFTER_MS = 20 * 1000;
