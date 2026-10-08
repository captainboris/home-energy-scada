import type { EChartsCoreOption } from "echarts/core";
import type { SeriesRow, ZoomRange } from "../types";

export const HISTORIAN_GRID = { left: 58, right: 18, top: 18, bottom: 44 } as const;

export const historianColours: Readonly<Record<string, string>> = {
  pv_power_kw: "#f5c451",
  load_power_kw: "#78adff",
  grid_import_power_kw: "#ff826e",
  grid_export_power_kw: "#66d1a4",
  battery_charge_power_kw: "#b58cff",
  battery_discharge_power_kw: "#ff9e54",
  battery_soc_pct: "#5dd8d0"
};

interface HistorianOptionsInput {
  id: string;
  unit: string;
  metrics: string[];
  series: SeriesRow[];
  fullRange: ZoomRange;
  zoom: ZoomRange;
  visibility: Record<string, boolean>;
  hoverTooltipEnabled: boolean;
  metricLabel: (metric: string) => string;
  formatTimestamp: (timestamp: number) => string;
}

export function buildHistorianOptions({
  id, unit, metrics, series, fullRange, zoom, visibility, hoverTooltipEnabled,
  metricLabel, formatTimestamp
}: HistorianOptionsInput) {
  const rows = new Map(series.map(row => [row.metric, row]));
  return {
    animation: false,
    backgroundColor: "transparent",
    grid: { ...HISTORIAN_GRID, containLabel: false },
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
        const lines = [formatTimestamp(timestamp)];
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
      name: metricLabel(metric),
      type: "line",
      data: visibility[metric] === false ? [] : rows.get(metric)?.points ?? [],
      showSymbol: false,
      symbol: "circle",
      connectNulls: true,
      sampling: "minmax",
      progressive: 5000,
      progressiveThreshold: 10000,
      lineStyle: { width: 1.4, color: historianColours[metric] },
      itemStyle: { color: historianColours[metric] },
      emphasis: { disabled: true }
    }))
  } satisfies EChartsCoreOption;
}
