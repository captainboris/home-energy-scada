import type { Point, Reading, SeriesRow } from "./types";

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
