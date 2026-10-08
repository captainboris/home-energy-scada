import type { HistoryData, LiveData, Point, Reading, SeriesRow } from "./types";

// Live packets belong only to the selected absolute range; the live cursor is
// separate and may extend beyond that range. Never pull old chart history in.
export function liveWithinRange(live: LiveData, start: number, end: number): LiveData {
  const includes = (timestamp: number) => timestamp >= start && timestamp < end;
  return {
    ...live,
    points: live.points.map(row => ({ ...row, points: row.points.filter(([t]) => includes(t)) })),
    latest: Object.fromEntries(Object.entries(live.latest).filter(([, point]) => includes(point.t)))
  };
}

export function appendLiveHistory(history: HistoryData, packet: LiveData): HistoryData {
  const live = liveWithinRange(packet, history.range.start_ms, history.range.end_ms);
  const latest = mergeLatest(history.latest, live.latest);
  const sourceTimestamp = latestSeriesTimestamp(live.points);
  const sourceTimes = [history.last_source_timestamp, sourceTimestamp, ...Object.values(live.latest).map(point => point.t)]
    .filter((timestamp): timestamp is number => timestamp != null);
  const lastSource = sourceTimes.length ? Math.max(...sourceTimes) : history.last_source_timestamp;
  const observedTimes = Object.values(latest).map(point => point.t);
  const observed = observedTimes.length ? Math.max(...observedTimes) : null;
  return {
    ...history,
    series: mergePointSeries(history.series, live.points),
    latest,
    latest_observed_at: observed != null ? new Date(observed).toISOString() : history.latest_observed_at,
    last_source_timestamp: lastSource,
    telemetry_health: live.health,
    checked_at: live.checked_at
  };
}

export function mergePointSeries(base: SeriesRow[], incoming: SeriesRow[]): SeriesRow[] {
  const rows = new Map<string, SeriesRow>();
  for (const source of [base, incoming]) {
    for (const row of source) {
      const existing = rows.get(row.metric) ?? { metric: row.metric, unit: row.unit, points: [] };
      const points = new Map<number, number | null>(existing.points.map(point => [point[0], point[1]]));
      for (const point of row.points) points.set(Number(point[0]), point[1]);
      existing.points = [...points.entries()].sort((a, b) => a[0] - b[0]) as Point[];
      rows.set(row.metric, existing);
    }
  }
  return [...rows.values()];
}

export function mergeLatest(
  base: Record<string, Reading>,
  incoming: Record<string, Reading>
): Record<string, Reading> {
  const next = { ...base };
  for (const [metric, point] of Object.entries(incoming)) {
    if (!next[metric] || Number(point.t) >= Number(next[metric].t)) next[metric] = point;
  }
  return next;
}

export function latestSeriesTimestamp(series: SeriesRow[]): number | null {
  let latest: number | null = null;
  for (const row of series) {
    for (const point of row.points) latest = latest === null ? point[0] : Math.max(latest, point[0]);
  }
  return latest;
}

export function ageLabel(sourceTimestamp: number | undefined, now: number, language: string) {
  if (!sourceTimestamp) return language === "en" ? "Waiting for first sample" : "等待首次采样";
  const seconds = Math.max(0, Math.floor((now - sourceTimestamp) / 1000));
  if (seconds < 60) return language === "en" ? `Updated ${seconds}s ago` : `${seconds} 秒前更新`;
  const minutes = Math.floor(seconds / 60);
  return language === "en" ? `Updated ${minutes}m ago` : `${minutes} 分钟前更新`;
}
