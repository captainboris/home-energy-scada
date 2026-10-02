import type { HistoryRange, Period, SeriesRow, ZoomRange } from "./types";

export const ZOOM_TOLERANCE_MS = 1000;
export const MIN_ZOOM_DURATION_MS = 1000;

export interface ZoomToolbarState {
  isZoomed: boolean;
  showRestore: boolean;
  showSync: boolean;
}

export interface NearestPoint {
  metric: string;
  pointIndex: number;
  timestamp: number;
}

export type TouchIntent = "pending" | "horizontal" | "vertical";

export function classifyTouchMovement(
  dx: number,
  dy: number,
  threshold = 12,
  horizontalConeRatio = 0.8,
  verticalDominanceRatio = 1.25
): TouchIntent {
  const horizontal = Math.abs(dx);
  const vertical = Math.abs(dy);
  if (horizontal < threshold && vertical < threshold) return "pending";
  // A natural horizontal range-selection may drift vertically. Lock it as
  // soon as the gesture enters a generous horizontal cone.
  if (horizontal >= threshold && horizontal >= vertical * horizontalConeRatio) return "horizontal";
  if (vertical >= threshold && vertical > horizontal * verticalDominanceRatio) return "vertical";
  return "pending";
}

export function normalizeZoom(range: ZoomRange): ZoomRange {
  return range.from <= range.to
    ? { from: range.from, to: range.to }
    : { from: range.to, to: range.from };
}

export function selectedPeriodRange(
  period: Pick<Period, "startMs" | "endMs">,
  responseRange?: Pick<HistoryRange, "start_ms" | "end_ms"> | null
): ZoomRange {
  return responseRange
    ? { from: responseRange.start_ms, to: responseRange.end_ms }
    : { from: period.startMs, to: period.endMs };
}

export function clampZoom(
  range: ZoomRange,
  full: ZoomRange,
  minimumDuration = MIN_ZOOM_DURATION_MS
): ZoomRange {
  const base = normalizeZoom(full);
  const requested = normalizeZoom(range);
  const from = Math.max(base.from, requested.from);
  const to = Math.min(base.to, requested.to);
  return to - from >= minimumDuration ? { from, to } : { ...base };
}

export function rangesEqual(
  left: ZoomRange,
  right: ZoomRange,
  tolerance = ZOOM_TOLERANCE_MS
): boolean {
  return Math.abs(left.from - right.from) <= tolerance
    && Math.abs(left.to - right.to) <= tolerance;
}

export function zoomToolbarState(
  local: ZoomRange,
  base: ZoomRange,
  lastSynced: ZoomRange,
  tolerance = ZOOM_TOLERANCE_MS
): ZoomToolbarState {
  const isZoomed = !rangesEqual(local, base, tolerance);
  return {
    isZoomed,
    showRestore: isZoomed,
    showSync: isZoomed && !rangesEqual(local, lastSynced, tolerance)
  };
}

export function timeAtPixel(
  x: number,
  plotLeft: number,
  plotRight: number,
  viewport: ZoomRange
): number {
  const width = Math.max(1, plotRight - plotLeft);
  const clampedX = Math.max(plotLeft, Math.min(plotRight, x));
  return viewport.from + (clampedX - plotLeft) / width * (viewport.to - viewport.from);
}

export function pixelAtTime(
  timestamp: number,
  plotLeft: number,
  plotRight: number,
  viewport: ZoomRange
): number {
  const duration = Math.max(1, viewport.to - viewport.from);
  return plotLeft + (timestamp - viewport.from) / duration * (plotRight - plotLeft);
}

export function dragZoomRange(
  startX: number,
  endX: number,
  plotLeft: number,
  plotRight: number,
  viewport: ZoomRange,
  base: ZoomRange,
  minimumPixels: number,
  minimumDuration = MIN_ZOOM_DURATION_MS
): ZoomRange | null {
  if (Math.abs(endX - startX) < minimumPixels || plotRight <= plotLeft) return null;
  const selected = normalizeZoom({
    from: timeAtPixel(startX, plotLeft, plotRight, viewport),
    to: timeAtPixel(endX, plotLeft, plotRight, viewport)
  });
  if (selected.to - selected.from < minimumDuration) return null;
  return clampZoom(selected, base, minimumDuration);
}

export function zoomAroundAnchor(
  viewport: ZoomRange,
  anchor: number,
  scale: number,
  base: ZoomRange,
  minimumDuration = MIN_ZOOM_DURATION_MS
): ZoomRange {
  const full = normalizeZoom(base);
  const current = clampZoom(viewport, full, minimumDuration);
  const fullDuration = full.to - full.from;
  const currentDuration = current.to - current.from;
  const targetDuration = Math.max(
    minimumDuration,
    Math.min(fullDuration, currentDuration * Math.max(0.01, scale))
  );
  if (targetDuration >= fullDuration - ZOOM_TOLERANCE_MS) return { ...full };

  const safeAnchor = Math.max(current.from, Math.min(current.to, anchor));
  const ratio = currentDuration > 0 ? (safeAnchor - current.from) / currentDuration : 0.5;
  let from = safeAnchor - ratio * targetDuration;
  let to = from + targetDuration;
  if (from < full.from) {
    to += full.from - from;
    from = full.from;
  }
  if (to > full.to) {
    from -= to - full.to;
    to = full.to;
  }
  return clampZoom({ from, to }, full, minimumDuration);
}

function nearestIndex(points: SeriesRow["points"], target: number): number | null {
  if (!points.length) return null;
  let low = 0;
  let high = points.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (points[middle][0] < target) low = middle + 1;
    else high = middle;
  }
  let before = low - 1;
  let after = low;
  while (before >= 0 || after < points.length) {
    const beforeDistance = before >= 0 ? Math.abs(points[before][0] - target) : Number.POSITIVE_INFINITY;
    const afterDistance = after < points.length ? Math.abs(points[after][0] - target) : Number.POSITIVE_INFINITY;
    const index = beforeDistance <= afterDistance ? before-- : after++;
    if (points[index][1] != null) return index;
  }
  return null;
}

export function nearestRealPoint(
  rows: SeriesRow[],
  metrics: string[],
  visibility: Record<string, boolean>,
  target: number,
  viewport: ZoomRange
): NearestPoint | null {
  let best: NearestPoint | null = null;
  for (const metric of metrics) {
    if (visibility[metric] === false) continue;
    const row = rows.find(candidate => candidate.metric === metric);
    if (!row) continue;
    const pointIndex = nearestIndex(row.points, target);
    if (pointIndex === null) continue;
    const timestamp = row.points[pointIndex][0];
    if (timestamp < viewport.from || timestamp > viewport.to) continue;
    if (!best || Math.abs(timestamp - target) < Math.abs(best.timestamp - target)) {
      best = { metric, pointIndex, timestamp };
    }
  }
  return best;
}

export function restoreAll(ids: string[], full: ZoomRange) {
  return Object.fromEntries(ids.map(id => [id, { ...full }])) as Record<string, ZoomRange>;
}

export function syncAll(ids: string[], source: ZoomRange) {
  return Object.fromEntries(ids.map(id => [id, { ...source }])) as Record<string, ZoomRange>;
}
