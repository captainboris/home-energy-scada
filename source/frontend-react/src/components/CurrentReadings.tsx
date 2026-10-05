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

  return <>
    <div className="section-heading">
      <h2>{t("overview.current")}</h2>
      <p className="muted">{t("overview.currentNote")}</p>
    </div>
    <div className="latest" aria-live="polite">
      <article className={`stat energy-flow-card${cards.pv.old ? " old" : ""}`}>
        <div className="label">{t("flow.pv")}</div>
        <div className="value">{valueLabel(pv?.value)}<span className="unit">kW</span></div>
        <FlowStatus state={typeof pv?.value !== "number"
          ? "unavailable"
          : pv.value >= FLOW_NEUTRAL_THRESHOLD_KW ? "generating" : "idle"} />
        <Freshness {...cards.pv} now={now} language={language} />
      </article>

      <article className={`stat energy-flow-card${cards.load.old ? " old" : ""}`}>
        <div className="label">{t("flow.homeLoad")}</div>
        <div className="value">{valueLabel(load?.value)}<span className="unit">kW</span></div>
        <div className="reading-secondary">{t("flow.householdDemand")}</div>
        <Freshness {...cards.load} now={now} language={language} />
      </article>

      <article className={`stat energy-flow-card battery-reading${cards.battery.old ? " old" : ""}`}>
        <div className="label">{t("flow.battery")}</div>
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

      <article className={`stat energy-flow-card${cards.grid.old ? " old" : ""}`}>
        <div className="label">{t("flow.grid")}</div>
        <div className="value">{valueLabel(grid.powerKw)}<span className="unit">kW</span></div>
        <FlowStatus
          state={grid.direction === "forward" ? "importing"
            : grid.direction === "reverse" ? "exporting"
              : grid.direction === "unknown" ? "unavailable" : "neutral"}
        />
        <Freshness {...cards.grid} now={now} language={language} />
      </article>
    </div>
  </>;
}
