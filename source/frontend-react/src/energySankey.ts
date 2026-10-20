import type { DailyData, Period } from "./types";

// These are report ports, not paired source-to-destination paths.
export const ENERGY_PORTS = [
  { key: "pv_kwh", side: "source", label: "sankey.pv", colour: "#f5c451" },
  { key: "grid_import_kwh", side: "source", label: "sankey.import", colour: "#78adff" },
  { key: "battery_discharge_kwh", side: "source", label: "sankey.discharge", colour: "#ba9bff" },
  { key: "load_kwh", side: "destination", label: "sankey.load", colour: "#59d6b0" },
  { key: "grid_export_kwh", side: "destination", label: "sankey.export", colour: "#60c9e8" },
  { key: "battery_charge_kwh", side: "destination", label: "sankey.charge", colour: "#edac83" }
] as const;

export type EnergyPortKey = typeof ENERGY_PORTS[number]["key"];
export const ENERGY_SANKEY_LAYOUT = { height: 350, top: 58, bottom: 16, nodeGap: 30 };
export type EnergyPortStatus = "official" | "missing" | "unavailable" | "notApplicable" | "unverified";
export interface EnergyPort {
  key: EnergyPortKey;
  side: "source" | "destination";
  label: string;
  colour: string;
  value: number | null;
  status: EnergyPortStatus;
  officialDays?: number;
  expectedDays?: number;
  source?: string;
  share: number | null;
}
export type SankeyNotice = "partial" | "installation" | "coverage" | "metadata" | "reports" | "warnings";
export interface EnergySankeyModel {
  mode: "loading" | "unsupported" | "unavailable" | "zero" | "sankey" | "proportions";
  ports: EnergyPort[];
  notices: SankeyNotice[];
  sources: number | null;
  destinations: number | null;
  difference: number | null;
  reportStart: string | null;
  reportEnd: string | null;
}

export function buildEnergySankey(data: DailyData | null, period: Period, today: string): EnergySankeyModel {
  const dates = data?.report_dates;
  const availability = data?.availability;
  const ports: EnergyPort[] = ENERGY_PORTS.map(port => {
    const raw = data?.energy?.[port.key];
    const value = typeof raw === "number" && Number.isFinite(raw) && raw >= 0 ? raw : null;
    const source = data?.metric_sources?.energy?.[port.key];
    const notApplicable = source?.startsWith("not_applicable_")
      || availability?.data_applicable === false
      || (port.key.startsWith("battery_") && (availability?.battery_applicable === false || data?.battery?.applicable === false));
    const status: EnergyPortStatus = notApplicable ? "notApplicable"
      : raw === undefined ? "missing" : value === null ? "unavailable"
      : source === "foxess_report_daily_sum" ? "official" : "unverified";
    return { ...port, value, status, source, share: null,
      officialDays: dates?.official_days_by_metric?.[port.key],
      expectedDays: dates?.expected_days_by_metric?.[port.key] };
  });
  const model: EnergySankeyModel = {
    mode: data ? "unavailable" : "loading", ports, notices: [],
    sources: null, destinations: null, difference: null,
    reportStart: dates?.start ?? null, reportEnd: dates?.end ?? null
  };
  if (!data) return model;
  // A stale payload must never be drawn under a newly selected period.
  if (data.range && (data.range.start_ms !== period.startMs || data.range.end_ms !== period.endMs)) {
    return { ...model, mode: "loading", ports: [], reportStart: null, reportEnd: null };
  }
  if (!data.range) {
    model.notices.push("metadata");
    return model;
  }
  if (period.fromTime !== "00:00" || period.toTime !== "00:00") {
    model.mode = "unsupported";
    return model;
  }
  if (period.fromDate <= today && today < period.toDate) model.notices.push("partial");
  if ((availability?.foxess_data_start_date && period.fromDate < availability.foxess_data_start_date)
    || (availability?.battery_install_date && period.fromDate < availability.battery_install_date)
    || ports.some(port => port.status === "notApplicable")) model.notices.push("installation");
  if (!dates?.start || !dates.end || dates.start < period.fromDate || dates.end >= period.toDate
    || dates.start > dates.end || data.timezone !== "Australia/Melbourne"
    || !availability?.foxess_data_start_date || !availability.battery_install_date) model.notices.push("metadata");
  if (ports.some(port => port.status !== "official")
    || data.warning_codes?.some(warning => warning.code === "OFFICIAL_REPORT_MISSING" || warning.code === "SUMMARY_MISSING")) {
    model.notices.push("reports");
  }
  // Equal date counts are a necessary check, never proof of hourly completeness.
  if (!dates || !Number.isInteger(dates.expected_days) || dates.expected_days <= 0
    || ports.some(port => port.expectedDays !== dates.expected_days || port.officialDays !== port.expectedDays)) {
    model.notices.push("coverage");
  }
  if (data.warnings?.length || data.warning_codes?.length) model.notices.push("warnings");
  if (model.notices.some(notice => notice !== "partial" && notice !== "warnings")) return model;
  const total = (side: EnergyPort["side"]) => ports.filter(port => port.side === side)
    .reduce((sum, port) => sum + port.value!, 0);
  model.sources = total("source");
  model.destinations = total("destination");
  // Range API energy has three decimal places. Round arithmetic noise only;
  // this is not a physical loss tolerance and never changes a link value.
  const difference = Number((model.sources - model.destinations).toFixed(3));
  model.difference = Object.is(difference, -0) ? 0 : difference;
  for (const port of ports) {
    const denominator = port.side === "source" ? model.sources : model.destinations;
    port.share = denominator > 0 ? port.value! / denominator * 100 : null;
  }
  model.mode = model.sources === 0 && model.destinations === 0 ? "zero" : "sankey";
  // ECharts 6 SankeyView clamps every edge to >=1px. Use a separate common-scale
  // proportion view when that would inflate a positive ribbon. This is solely
  // a renderer constraint, not an energy/loss threshold. The six ports remain unchanged.
  const { height, top, bottom, nodeGap } = ENERGY_SANKEY_LAYOUT;
  const scale = (height - top - bottom - nodeGap * 2) / Math.max(model.sources, model.destinations);
  if (model.mode === "sankey" && ports.some(port => port.value! > 0 && port.value! * scale < 1)) model.mode = "proportions";
  return model;
}

export function buildEnergySankeyOptions(model: EnergySankeyModel, label: (key: string) => string,
  format: (value: number) => string, tooltip: (port?: EnergyPort) => HTMLElement | string) {
  const ports = model.ports;
  return {
    animation: false,
    tooltip: {
      trigger: "item" as const, triggerOn: "mousemove|click", confine: true, enterable: false,
      className: "energy-sankey-tooltip",
      backgroundColor: "#091220", borderColor: "#4a607d", textStyle: { color: "#dce6f4", fontSize: 12 },
      extraCssText: "white-space:pre-line;max-width:260px;",
      formatter: (params: { data?: { metric?: string; name?: string } }) => tooltip(
        ports.find(port => port.key === (params.data?.metric ?? params.data?.name)))
    },
    series: [{
      type: "sankey" as const, left: 100, right: 100, top: ENERGY_SANKEY_LAYOUT.top, bottom: ENERGY_SANKEY_LAYOUT.bottom,
      nodeWidth: 16, nodeGap: ENERGY_SANKEY_LAYOUT.nodeGap, layoutIterations: 0, nodeAlign: "justify" as const,
      draggable: false, emphasis: { disabled: true },
      data: [
        ...ports.map(port => ({
          name: port.key, metric: port.key, depth: port.side === "source" ? 0 : 2,
          itemStyle: { color: port.colour, borderWidth: 0 },
          label: {
            position: port.side === "source" ? "left" as const : "right" as const,
            color: "#dce6f4", fontSize: 11, lineHeight: 16,
            formatter: `${label(port.label)}\n${format(port.value!)} kWh`
          }
        })),
        { name: "pool", depth: 1, itemStyle: { color: "#526279", borderColor: "#8090a8", borderWidth: 1 },
          label: { position: "top" as const, color: "#b8c6d9", fontSize: 11, lineHeight: 16, formatter: label("sankey.pool") } }
      ],
      // A zero-width edge must be absent: ECharts would draw even zero as 1px.
      links: ports.filter(port => port.value! > 0).map(port => ({
        source: port.side === "source" ? port.key : "pool",
        target: port.side === "source" ? "pool" : port.key,
        value: port.value!, metric: port.key,
        lineStyle: { color: port.colour, opacity: 0.36, curveness: 0.45 }
      }))
    }]
  };
}
