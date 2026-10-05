import { useCallback, useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { LineChart } from "echarts/charts";
import {
  DataZoomComponent,
  GridComponent,
  TooltipComponent
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { ECharts, EChartsCoreOption } from "echarts/core";
import type { SeriesRow, ZoomRange } from "../types";
import { t, UI, useLanguage } from "../ui";
import {
  clampZoom,
  classifyTouchMovement,
  dragZoomRange,
  nearestRealPoint,
  pixelAtTime,
  rangesEqual,
  timeAtPixel,
  zoomAroundAnchor,
  zoomToolbarState
} from "../zoom";

echarts.use([LineChart, DataZoomComponent, GridComponent, TooltipComponent, CanvasRenderer]);

const GRID_LEFT = 58;
const GRID_RIGHT = 18;
const GRID_TOP = 18;
const GRID_BOTTOM = 44;
const DESKTOP_DRAG_THRESHOLD = 8;
const TOUCH_DRAG_THRESHOLD = 12;
const TOUCH_HORIZONTAL_CONE_RATIO = 0.8;
const TOUCH_VERTICAL_DOMINANCE_RATIO = 1.25;
const TOUCH_POINT_HIT_PX = 28;

const colours: Record<string, string> = {
  pv_power_kw: "#f5c451",
  load_power_kw: "#78adff",
  grid_import_power_kw: "#ff826e",
  grid_export_power_kw: "#66d1a4",
  battery_charge_power_kw: "#b58cff",
  battery_discharge_power_kw: "#ff9e54",
  battery_soc_pct: "#5dd8d0"
};

type GestureMode = "pending" | "selecting" | "vertical";

interface PointerGesture {
  pointerId: number;
  pointerType: string;
  mode: GestureMode;
  startX: number;
  startY: number;
  lastX: number;
  lastY: number;
  viewport: ZoomRange;
}

function numeric(value: unknown): number | null {
  const result = Number(value);
  return Number.isFinite(result) ? result : null;
}

function readZoom(chart: ECharts, full: ZoomRange): ZoomRange {
  const option = chart.getOption() as { dataZoom?: Array<Record<string, unknown>> };
  const zoom = option.dataZoom?.[0] ?? {};
  let from = numeric(zoom.startValue);
  let to = numeric(zoom.endValue);
  if (from === null || to === null) {
    const start = numeric(zoom.start) ?? 0;
    const end = numeric(zoom.end) ?? 100;
    from = full.from + (full.to - full.from) * start / 100;
    to = full.from + (full.to - full.from) * end / 100;
  }
  return clampZoom({ from, to }, full);
}

function sameToolbar(
  left: ReturnType<typeof zoomToolbarState>,
  right: ReturnType<typeof zoomToolbarState>
) {
  return left.isZoomed === right.isZoomed
    && left.showRestore === right.showRestore
    && left.showSync === right.showSync;
}

export function HistorianChart({
  id,
  titleKey,
  unit,
  metrics,
  series,
  fullRange,
  visibility,
  onVisibilityChange,
  syncCommand,
  restoreVersion,
  onSync,
  onRestore
}: {
  id: string;
  titleKey: string;
  unit: string;
  metrics: string[];
  series: SeriesRow[];
  fullRange: ZoomRange;
  visibility: Record<string, boolean>;
  onVisibilityChange: (metric: string, visible: boolean) => void;
  syncCommand: { version: number; range: ZoomRange } | null;
  restoreVersion: number;
  onSync: (range: ZoomRange) => void;
  onRestore: () => void;
}) {
  const host = useRef<HTMLDivElement | null>(null);
  const selectionOverlay = useRef<HTMLDivElement | null>(null);
  const instance = useRef<ECharts | null>(null);
  const localZoom = useRef<ZoomRange>({ ...fullRange });
  const lastSyncedZoom = useRef<ZoomRange>({ ...fullRange });
  const fullRangeRef = useRef(fullRange);
  const seriesRef = useRef(series);
  const visibilityRef = useRef(visibility);
  const tooltipPinned = useRef(false);
  const [toolbar, setToolbar] = useState(() => zoomToolbarState(fullRange, fullRange, fullRange));
  const { language } = useLanguage();
  const hoverTooltipEnabled = typeof window.matchMedia !== "function"
    || window.matchMedia("(hover: hover) and (pointer: fine)").matches;

  fullRangeRef.current = fullRange;
  seriesRef.current = series;
  visibilityRef.current = visibility;

  const updateLocalZoom = useCallback((range: ZoomRange) => {
    const next = clampZoom(range, fullRangeRef.current);
    localZoom.current = next;
    const nextToolbar = zoomToolbarState(next, fullRangeRef.current, lastSyncedZoom.current);
    setToolbar(previous => sameToolbar(previous, nextToolbar) ? previous : nextToolbar);
    return next;
  }, []);

  const dispatchZoom = useCallback((range: ZoomRange) => {
    const next = updateLocalZoom(range);
    instance.current?.dispatchAction({
      type: "dataZoom",
      dataZoomId: `inside-${id}`,
      startValue: next.from,
      endValue: next.to
    });
  }, [id, updateLocalZoom]);

  useEffect(() => {
    const element = host.current;
    if (!element) return;
    const chart = echarts.init(element, undefined, { renderer: "canvas" });
    instance.current = chart;
    const activeTouchPointers = new Set<number>();
    const dismissedTooltipPointers = new Set<number>();
    let multiTouch = false;
    let gesture: PointerGesture | null = null;

    const plotBounds = () => ({
      left: GRID_LEFT,
      right: Math.max(GRID_LEFT + 1, element.clientWidth - GRID_RIGHT),
      top: GRID_TOP,
      bottom: Math.max(GRID_TOP + 1, element.clientHeight - GRID_BOTTOM)
    });
    const localPoint = (event: PointerEvent | WheelEvent) => {
      const rect = element.getBoundingClientRect();
      return { x: event.clientX - rect.left, y: event.clientY - rect.top };
    };
    const insidePlot = (x: number, y: number) => {
      try {
        return chart.containPixel({ gridIndex: 0 }, [x, y]);
      } catch {
        return false;
      }
    };
    const hideSelection = () => {
      gesture = null;
      element.classList.remove("is-selecting");
      if (selectionOverlay.current) selectionOverlay.current.hidden = true;
    };
    const hideTooltip = () => {
      tooltipPinned.current = false;
      chart.dispatchAction({ type: "hideTip" });
    };
    const tooltipContains = (clientX: number, clientY: number) => {
      const tooltip = element.querySelector<HTMLElement>(".historian-tooltip");
      if (!tooltip || tooltip.offsetWidth === 0 || tooltip.offsetHeight === 0) return false;
      const rect = tooltip.getBoundingClientRect();
      return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
    };
    const drawSelection = (current: PointerGesture, endX: number) => {
      const overlay = selectionOverlay.current;
      if (!overlay) return;
      const bounds = plotBounds();
      const start = Math.max(bounds.left, Math.min(bounds.right, current.startX));
      const finish = Math.max(bounds.left, Math.min(bounds.right, endX));
      overlay.hidden = false;
      overlay.style.left = `${Math.min(start, finish)}px`;
      overlay.style.top = `${bounds.top}px`;
      overlay.style.width = `${Math.max(1, Math.abs(finish - start))}px`;
      overlay.style.height = `${Math.max(1, bounds.bottom - bounds.top)}px`;
    };
    const showTouchTooltip = (x: number, y: number) => {
      const bounds = plotBounds();
      const viewport = localZoom.current;
      const target = timeAtPixel(x, bounds.left, bounds.right, viewport);
      const point = nearestRealPoint(seriesRef.current, metrics, visibilityRef.current, target, viewport);
      if (!point) {
        hideTooltip();
        return;
      }
      const pointX = pixelAtTime(point.timestamp, bounds.left, bounds.right, viewport);
      if (Math.abs(pointX - x) > TOUCH_POINT_HIT_PX) {
        hideTooltip();
        return;
      }
      tooltipPinned.current = true;
      chart.dispatchAction({
        type: "showTip",
        x: pointX,
        y: Math.max(bounds.top, Math.min(bounds.bottom, y))
      });
    };
    const finishTouchPointer = (pointerId: number) => {
      activeTouchPointers.delete(pointerId);
      if (activeTouchPointers.size === 0) multiTouch = false;
    };
    const dataZoom = () => { updateLocalZoom(readZoom(chart, fullRangeRef.current)); };
    const pointerDown = (event: PointerEvent) => {
      const touchLike = event.pointerType !== "mouse";
      if (!touchLike && event.button !== 0) return;
      if (touchLike) activeTouchPointers.add(event.pointerId);
      if (touchLike && tooltipPinned.current && tooltipContains(event.clientX, event.clientY)) {
        dismissedTooltipPointers.add(event.pointerId);
        event.preventDefault();
        event.stopPropagation();
        hideTooltip();
        return;
      }
      if (touchLike && activeTouchPointers.size > 1) {
        multiTouch = true;
        hideSelection();
        return;
      }
      const point = localPoint(event);
      if (!insidePlot(point.x, point.y)) return;
      gesture = {
        pointerId: event.pointerId,
        pointerType: event.pointerType,
        mode: "pending",
        startX: point.x,
        startY: point.y,
        lastX: point.x,
        lastY: point.y,
        viewport: { ...localZoom.current }
      };
    };
    const pointerMove = (event: PointerEvent) => {
      if (!gesture || gesture.pointerId !== event.pointerId || multiTouch) return;
      const point = localPoint(event);
      gesture.lastX = point.x;
      gesture.lastY = point.y;
      const dx = point.x - gesture.startX;
      const dy = point.y - gesture.startY;
      const touchLike = gesture.pointerType !== "mouse";
      const threshold = touchLike ? TOUCH_DRAG_THRESHOLD : DESKTOP_DRAG_THRESHOLD;

      if (gesture.mode === "pending") {
        const touchIntent = touchLike
          ? classifyTouchMovement(
            dx,
            dy,
            threshold,
            TOUCH_HORIZONTAL_CONE_RATIO,
            TOUCH_VERTICAL_DOMINANCE_RATIO
          )
          : "pending";
        if (touchIntent === "vertical") {
          gesture.mode = "vertical";
          return;
        }
        if (touchLike ? touchIntent !== "horizontal" : Math.abs(dx) < threshold) return;
        gesture.mode = "selecting";
        element.classList.add("is-selecting");
        hideTooltip();
        try { element.setPointerCapture(event.pointerId); } catch { /* pointer may already be cancelled */ }
      }
      if (gesture.mode !== "selecting") return;
      event.preventDefault();
      event.stopPropagation();
      drawSelection(gesture, point.x);
    };
    const pointerUp = (event: PointerEvent) => {
      const touchLike = event.pointerType !== "mouse";
      if (dismissedTooltipPointers.delete(event.pointerId)) {
        if (touchLike) finishTouchPointer(event.pointerId);
        return;
      }
      if (multiTouch) {
        if (gesture?.pointerId === event.pointerId) hideSelection();
        if (touchLike) finishTouchPointer(event.pointerId);
        return;
      }
      const current = gesture?.pointerId === event.pointerId ? gesture : null;
      if (current?.mode === "selecting") {
        event.preventDefault();
        event.stopPropagation();
        current.lastX = localPoint(event).x;
        const bounds = plotBounds();
        const selected = dragZoomRange(
          current.startX,
          current.lastX,
          bounds.left,
          bounds.right,
          current.viewport,
          fullRangeRef.current,
          touchLike ? TOUCH_DRAG_THRESHOLD : DESKTOP_DRAG_THRESHOLD
        );
        hideSelection();
        if (selected) dispatchZoom(selected);
      } else if (current?.mode === "pending" && touchLike) {
        const point = localPoint(event);
        showTouchTooltip(point.x, point.y);
        hideSelection();
      } else if (current) {
        hideSelection();
      }
      try {
        if (element.hasPointerCapture(event.pointerId)) element.releasePointerCapture(event.pointerId);
      } catch { /* no active capture */ }
      if (touchLike) finishTouchPointer(event.pointerId);
    };
    const pointerCancel = (event: PointerEvent) => {
      dismissedTooltipPointers.delete(event.pointerId);
      if (gesture?.pointerId === event.pointerId) hideSelection();
      if (event.pointerType !== "mouse") finishTouchPointer(event.pointerId);
    };
    const wheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.deltaY === 0 || gesture?.mode === "selecting") return;
      const point = localPoint(event);
      if (!insidePlot(point.x, point.y)) return;
      event.preventDefault();
      event.stopPropagation();
      hideTooltip();
      const bounds = plotBounds();
      const viewport = localZoom.current;
      const anchor = timeAtPixel(point.x, bounds.left, bounds.right, viewport);
      const delta = Math.max(-600, Math.min(600, event.deltaY));
      const scale = Math.max(0.5, Math.min(2, Math.exp(delta * 0.0015)));
      const next = zoomAroundAnchor(viewport, anchor, scale, fullRangeRef.current);
      if (!rangesEqual(next, viewport, 0.5)) dispatchZoom(next);
    };

    chart.on("datazoom", dataZoom);
    chart.getZr().on("dblclick", onRestore);
    element.addEventListener("pointerdown", pointerDown, { capture: true, passive: false });
    element.addEventListener("pointermove", pointerMove, { capture: true, passive: false });
    element.addEventListener("pointerup", pointerUp, { capture: true, passive: false });
    element.addEventListener("pointercancel", pointerCancel, { capture: true, passive: false });
    element.addEventListener("wheel", wheel, { capture: true, passive: false });
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element);
    return () => {
      observer.disconnect();
      element.removeEventListener("pointerdown", pointerDown, true);
      element.removeEventListener("pointermove", pointerMove, true);
      element.removeEventListener("pointerup", pointerUp, true);
      element.removeEventListener("pointercancel", pointerCancel, true);
      element.removeEventListener("wheel", wheel, true);
      chart.dispose();
      instance.current = null;
    };
  }, [dispatchZoom, metrics, onRestore, updateLocalZoom]);

  useEffect(() => {
    const chart = instance.current;
    if (!chart) return;
    const zoom = clampZoom(localZoom.current, fullRange);
    const rows = new Map(series.map(row => [row.metric, row]));
    const option: EChartsCoreOption = {
      animation: false,
      backgroundColor: "transparent",
      grid: { left: GRID_LEFT, right: GRID_RIGHT, top: GRID_TOP, bottom: GRID_BOTTOM, containLabel: false },
      tooltip: {
        trigger: "axis",
        triggerOn: hoverTooltipEnabled ? "mousemove" : "none",
        enterable: true,
        className: "historian-tooltip",
        confine: true,
        transitionDuration: 0,
        backgroundColor: "rgba(9,18,32,.96)",
        borderColor: "#4a607d",
        textStyle: { color: "#e8f0fb", fontSize: 12 },
        axisPointer: { type: "line", lineStyle: { color: "#a8b8cf", type: "dashed" } },
        formatter: (input: unknown) => {
          const items = (Array.isArray(input) ? input : [input]) as Array<{
            data?: [number, number | null]; seriesName?: string; color?: string
          }>;
          const real = items.filter(item => Array.isArray(item.data) && item.data[1] != null);
          if (!real.length) return "";
          const timestamp = Number(real[0].data?.[0]);
          const lines = [UI.stampLabel(timestamp, true)];
          for (const item of real) {
            const value = Number(item.data?.[1]);
            lines.push(`${item.seriesName}: ${value.toFixed(unit === "%" ? 0 : 2)} ${unit}`);
          }
          return lines.join("<br>");
        }
      },
      xAxis: {
        type: "time",
        min: fullRange.from,
        max: fullRange.to,
        boundaryGap: false,
        axisLine: { lineStyle: { color: "#33445d" } },
        axisTick: { show: false },
        axisLabel: { color: "#91a8c7", hideOverlap: true },
        splitLine: { show: false }
      },
      yAxis: {
        type: "value",
        min: 0,
        max: unit === "%" ? 100 : undefined,
        scale: unit !== "%",
        axisLabel: { color: "#91a8c7", formatter: `{value} ${unit}` },
        axisLine: { show: false },
        axisTick: { show: false },
        splitLine: { lineStyle: { color: "#28364c" } }
      },
      dataZoom: [{
        id: `inside-${id}`,
        type: "inside",
        xAxisIndex: 0,
        filterMode: "filter",
        startValue: zoom.from,
        endValue: zoom.to,
        disabled: true,
        zoomOnMouseWheel: false,
        moveOnMouseWheel: false,
        moveOnMouseMove: false,
        preventDefaultMouseMove: false,
        zoomLock: false,
        throttle: 40
      }],
      series: metrics.map(metric => ({
        id: metric,
        name: t(`metric.${metric}`),
        type: "line",
        data: visibility[metric] === false ? [] : rows.get(metric)?.points ?? [],
        showSymbol: false,
        symbol: "circle",
        connectNulls: true,
        sampling: "minmax",
        progressive: 5000,
        progressiveThreshold: 10000,
        lineStyle: { width: 1.4, color: colours[metric] },
        itemStyle: { color: colours[metric] },
        emphasis: { disabled: true }
      }))
    };
    chart.setOption(option, { notMerge: false, lazyUpdate: true });
  }, [fullRange.from, fullRange.to, hoverTooltipEnabled, id, language, metrics, series, unit, visibility]);

  useEffect(() => {
    lastSyncedZoom.current = { ...fullRange };
    updateLocalZoom(fullRange);
    instance.current?.dispatchAction({
      type: "dataZoom",
      dataZoomId: `inside-${id}`,
      startValue: fullRange.from,
      endValue: fullRange.to
    });
  }, [fullRange.from, fullRange.to, id, updateLocalZoom]);

  useEffect(() => {
    if (!syncCommand || !instance.current) return;
    const next = clampZoom(syncCommand.range, fullRangeRef.current);
    lastSyncedZoom.current = next;
    updateLocalZoom(next);
    tooltipPinned.current = false;
    instance.current.dispatchAction({ type: "hideTip" });
    instance.current.dispatchAction({
      type: "dataZoom",
      dataZoomId: `inside-${id}`,
      startValue: next.from,
      endValue: next.to
    });
  }, [id, syncCommand?.version, updateLocalZoom]);

  useEffect(() => {
    if (!instance.current) return;
    const base = { ...fullRangeRef.current };
    lastSyncedZoom.current = base;
    updateLocalZoom(base);
    tooltipPinned.current = false;
    instance.current.dispatchAction({ type: "hideTip" });
    instance.current.dispatchAction({
      type: "dataZoom",
      dataZoomId: `inside-${id}`,
      startValue: base.from,
      endValue: base.to
    });
  }, [id, restoreVersion, updateLocalZoom]);

  const sync = () => onSync(localZoom.current);
  return <section
    className="chart-card"
    data-chart-id={id}
    data-base-from={String(fullRange.from)}
    data-base-to={String(fullRange.to)}
    data-zoomed={toolbar.isZoomed ? "true" : "false"}
    data-sync-dirty={toolbar.showSync ? "true" : "false"}
  >
    <div className="chart-head">
      <h2>{t(titleKey)}</h2>
      {(toolbar.showSync || toolbar.showRestore) && <div className="chart-actions">
        {toolbar.showSync && <button type="button" onClick={sync} aria-label={t("chart.syncLabel")}>{t("chart.sync")}</button>}
        {toolbar.showRestore && <button type="button" onClick={onRestore} aria-label={t("chart.restoreLabel")}>{t("chart.reset")}</button>}
      </div>}
    </div>
    <div className="legend chart-legend" role="group" aria-label={t(titleKey)}>
      {metrics.map(metric => {
        const checked = visibility[metric] !== false;
        return <label key={metric} className={checked ? "" : "off"}>
          <input
            type="checkbox"
            checked={checked}
            onChange={event => onVisibilityChange(metric, event.target.checked)}
            style={{ accentColor: colours[metric] }}
          />
          <span>{t(`metric.${metric}`)}</span>
        </label>;
      })}
    </div>
    <div className="echart-shell">
      <div ref={host} className="echart" role="img" aria-label={`${t(titleKey)}, ${unit}`} />
      <div ref={selectionOverlay} className="zoom-selection" hidden aria-hidden="true" />
    </div>
    <div className="chart-hint">{t("chart.echartsHint")}</div>
  </section>;
}
