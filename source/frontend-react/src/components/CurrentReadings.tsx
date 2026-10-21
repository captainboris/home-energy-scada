import { useEffect, useState } from "react";
import type { Reading, TelemetryHealth } from "../types";
import { ageLabel } from "../data";
import {
  BATTERY_CAPACITY_KWH,
  FLOW_NEUTRAL_THRESHOLD_KW,
  REALTIME_FRESHNESS_LABEL_AFTER_MS,
  REALTIME_STALE_AFTER_MS
} from "../config";
import { directionalFlow, estimatedRemainingEnergyKwh, latestTimestamp } from "../energyFlow";
import { UI, t, useLanguage } from "../ui";
// The existing Web CSP permits data: images only; Vite inlines this static asset.
import house from "../assets/current-house.webp?inline";
import "./CurrentReadings.css";

function ReadingIcon({ kind }: { kind: "pv" | "load" | "grid" | "battery" }) {
  return <svg className={`reading-icon icon-${kind}`} viewBox="0 0 32 32" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
    {kind === "pv" ? <><circle cx="16" cy="16" r="6" fill="currentColor" /><path d="M16 1v5m0 20v5M1 16h5m20 0h5M5 5l4 4m14 14 4 4M5 27l4-4M23 9l4-4" /></>
      : kind === "load" ? <><path d="M3 15 16 3l13 12M7 12v17h18V12" /><path d="M13 29V18h6v11" /></>
      : kind === "grid" ? <path d="M12 3h8l5 27M12 3 7 30M16 3v27M4 12h24M2 20h28M11 6l12 20M21 6 9 26M7 30l18-10M25 30 7 20" />
      : <><path d="M7 6h18v24H7zM12 6V2h8v4M16 12v12m-4-6h8" /></>}
  </svg>;
}

/** Geometry follows the static scene. Direction comes only from existing channel helpers. */
function PowerPath({ kind, path, active, reverse = false }: {
  kind: "pv" | "load" | "grid" | "battery";
  path: string;
  active: boolean;
  reverse?: boolean;
}) {
  return <g className={`power-path power-${kind}${active ? " is-flowing" : ""}`}
    data-flow={kind} data-direction={active ? reverse ? "reverse" : "forward" : "inactive"}>
    <path className="power-track" d={path} />
    {active && [0, 1, 2].map(index => <g className="power-arrow" key={index}>
      <path d="M-9-7 0 0-9 7" transform={reverse ? "rotate(180)" : undefined} />
      <animateMotion path={path} dur="2.4s" begin={`${-index * 0.8}s`} repeatCount="indefinite"
        rotate="auto" keyPoints={reverse ? "1;0" : "0;1"} keyTimes="0;1" calcMode="linear" />
    </g>)}
  </g>;
}

function valueLabel(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function isOld(timestamp: number | null, now: number, health?: TelemetryHealth) {
  return !timestamp || now - timestamp > REALTIME_STALE_AFTER_MS || health?.healthy === false;
}

function Freshness({ timestamp, old, now, language }: {
  timestamp: number | null;
  old: boolean;
  now: number;
  language: string;
}) {
  const showAge = timestamp != null && now - timestamp > REALTIME_FRESHNESS_LABEL_AFTER_MS;
  return <div className="reading-footer">
    {showAge && <span className="time">{ageLabel(timestamp, now, language)}</span>}
    {old && <span className="stale-label">{t("flow.stale")}</span>}
  </div>;
}

function FlowStatus({ state, powerKw }: {
  state: "generating" | "charging" | "discharging" | "importing" | "exporting" | "idle" | "neutral" | "unavailable";
  powerKw?: number | null;
}) {
  const showPower = typeof powerKw === "number" && state !== "idle" && state !== "neutral";
  return <div className={`flow-status flow-${state}`}>
    <span className="flow-dot" aria-hidden="true" />
    <span>{t(`flow.${state}`)}</span>
    {showPower && <strong>{powerKw.toFixed(2)} kW</strong>}
  </div>;
}

export function CurrentReadings({ latest, health }: {
  latest: Record<string, Reading>;
  health?: TelemetryHealth;
}) {
  const [now, setNow] = useState(Date.now());
  const { language } = useLanguage();
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);

  const pv = latest.pv_power_kw;
  const load = latest.load_power_kw;
  const soc = latest.battery_soc_pct;
  const battery = directionalFlow(
    latest.battery_charge_power_kw,
    latest.battery_discharge_power_kw
  );
  const grid = directionalFlow(
    latest.grid_import_power_kw,
    latest.grid_export_power_kw
  );
  const batteryTimestamp = latestTimestamp(
    soc,
    latest.battery_charge_power_kw,
    latest.battery_discharge_power_kw
  );
  const socState = soc?.value != null ? UI.socState(Number(soc.value)) : null;
  const remaining = estimatedRemainingEnergyKwh(soc?.value, BATTERY_CAPACITY_KWH);
  const pvTimestamp = latestTimestamp(pv);
  const loadTimestamp = latestTimestamp(load);
  const cards = {
    pv: { timestamp: pvTimestamp, old: isOld(pvTimestamp, now, health) },
    load: { timestamp: loadTimestamp, old: isOld(loadTimestamp, now, health) },
    battery: { timestamp: batteryTimestamp, old: isOld(batteryTimestamp, now, health) },
    grid: { timestamp: grid.timestamp, old: isOld(grid.timestamp, now, health) }
  };

  return <section className="current-readings" aria-labelledby="current-readings-title">
    <div className="readings-scene">
      <img className="readings-house" src={house} alt="" width="1557" height="1010" />
      <h2 id="current-readings-title">{t("overview.current")}</h2>
      <svg className="readings-flows" viewBox="0 0 1557 1010" aria-hidden="true">
        <PowerPath kind="pv" path="M590 411 L570 441 L570 516"
          active={!cards.pv.old && Number.isFinite(pv?.value) && pv.value! >= FLOW_NEUTRAL_THRESHOLD_KW} />
        <PowerPath kind="grid" path="M325 530 L400 530 L455 560 L521 575"
          active={!cards.grid.old && (grid.direction === "forward" || grid.direction === "reverse")}
          reverse={grid.direction === "reverse"} />
        <PowerPath kind="load" path="M589 591 L624 616 L705 643"
          active={!cards.load.old && Number.isFinite(load?.value) && load.value! >= FLOW_NEUTRAL_THRESHOLD_KW} />
        <PowerPath kind="battery" path="M560 624 L541 646 L541 727 L568 742"
          active={!isOld(battery.timestamp, now, health) && (battery.direction === "forward" || battery.direction === "reverse")}
          reverse={battery.direction === "reverse"} />
      </svg>
    </div>
    <div className="latest readings-panels" aria-live="polite">
      <article className={`stat energy-flow-card reading-pv${cards.pv.old ? " old" : ""}`}>
        <ReadingIcon kind="pv" /><div className="label">{t("flow.pv")}</div>
        <div className="value">{valueLabel(pv?.value)}<span className="unit">kW</span></div>
        <FlowStatus state={typeof pv?.value !== "number"
          ? "unavailable"
          : pv.value >= FLOW_NEUTRAL_THRESHOLD_KW ? "generating" : "idle"} />
        <Freshness {...cards.pv} now={now} language={language} />
      </article>

      <article className={`stat energy-flow-card reading-load${cards.load.old ? " old" : ""}`}>
        <ReadingIcon kind="load" /><div className="label">{t("flow.homeLoad")}</div>
        <div className="value">{valueLabel(load?.value)}<span className="unit">kW</span></div>
        <Freshness {...cards.load} now={now} language={language} />
      </article>

      <article className={`stat energy-flow-card reading-battery battery-reading${cards.battery.old ? " old" : ""}`}>
        <ReadingIcon kind="battery" /><div className="label">{t("flow.battery")}</div>
        <div className="battery-values">
          <div className={`value${socState ? ` ${socState.className}` : ""}`}>
            {valueLabel(soc?.value, 0)}<span className="unit">%</span>
          </div>
          <div className="estimated-energy" title={t("flow.estimatedEnergyTitle", { capacity: BATTERY_CAPACITY_KWH })}>
            ≈ {valueLabel(remaining, 1)} kWh
          </div>
        </div>
        <FlowStatus
          state={battery.direction === "forward" ? "charging"
            : battery.direction === "reverse" ? "discharging"
              : battery.direction === "unknown" ? "unavailable" : "idle"}
          powerKw={battery.powerKw}
        />
        <div className="battery-meta">
          {socState && <span className={`soc-label ${socState.className}`}>{socState.label}</span>}
          <Freshness {...cards.battery} now={now} language={language} />
        </div>
      </article>

      <article className={`stat energy-flow-card reading-grid${cards.grid.old ? " old" : ""}`}>
        <ReadingIcon kind="grid" /><div className="label">{t("flow.grid")}</div>
        <div className="value">{valueLabel(grid.powerKw)}<span className="unit">kW</span></div>
        <FlowStatus
          state={grid.direction === "forward" ? "importing"
            : grid.direction === "reverse" ? "exporting"
              : grid.direction === "unknown" ? "unavailable" : "neutral"}
        />
        <Freshness {...cards.grid} now={now} language={language} />
      </article>
    </div>
  </section>;
}
