import { useCallback, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { DailyData, Period } from "./types";
import { UI, t, useLanguage } from "./ui";
import { useSession } from "./useSession";
import { Header, PageState, formatRange } from "./components/AppChrome";
import { PeriodNavigator } from "./components/PeriodNavigator";
import { KpiCard } from "./components/KpiCard";

const energyCards = [
  ["energy.pv", "pv_kwh"], ["energy.load", "load_kwh"],
  ["energy.import", "grid_import_kwh"], ["energy.export", "grid_export_kwh"],
  ["energy.charge", "battery_charge_kwh"], ["energy.discharge", "battery_discharge_kwh"]
] as const;

function fmt(value: unknown, digits = 2) {
  return typeof value === "number" && Number.isFinite(value) ? value.toFixed(digits) : "—";
}

function Daily() {
  const session = useSession();
  useLanguage();
  const [period, setPeriod] = useState<Period>(() => UI.periodFromUrl());
  const [data, setData] = useState<DailyData | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");

  const loadRef = useRef<(manual?: boolean) => void>(() => undefined);
  const stopRef = useRef<() => void>(() => undefined);
  const load = useCallback((manual = false) => loadRef.current(manual), []);

  // One period/session owner controls requests and completion-based polling.
  useEffect(() => {
    if (session.phase !== "app") return;
    let active = true;
    let inFlight = false;
    let checkOnResume = false;
    let timer: number | null = null;
    const clearTimer = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
    };
    const read = async (manual = false) => {
      if (!active || inFlight || document.hidden) return;
      clearTimer();
      inFlight = true;
      checkOnResume = false;
      setBusy(true);
      setError("");
      setStatus(t("status.readingAnalytics"));
      try {
        const params = new URLSearchParams(UI.periodQuery(period));
        const body = await session.request<{ data: DailyData }>(`/api/summary/range?${params}`);
        if (!active) return;
        setData(body.data);
        setStatus(document.hidden ? t("status.paused")
          : manual ? t("status.reloadedAnalytics") : t("status.checkedAnalytics"));
      } catch (reason) {
        if (!active) return;
        const apiError = reason as Error & { status?: number };
        if (apiError.status === 401) {
          stop();
          setBusy(false);
          session.showLogin(apiError.message);
        } else {
          setError(apiError.message);
          setStatus(document.hidden ? t("status.paused") : t("status.failed"));
        }
      } finally {
        inFlight = false;
        if (active) {
          setBusy(false);
          if (!document.hidden) {
            if (checkOnResume) void read(false);
            else timer = window.setTimeout(() => void read(false), 60000);
          }
        }
      }
    };
    const visible = () => {
      clearTimer();
      if (document.hidden) setStatus(t("status.paused"));
      else if (inFlight) checkOnResume = true;
      else void read(false);
    };
    const stop = () => {
      active = false;
      clearTimer();
      document.removeEventListener("visibilitychange", visible);
    };
    stopRef.current = stop;
    loadRef.current = read;
    document.addEventListener("visibilitychange", visible);
    if (document.hidden) { setBusy(false); setStatus(t("status.paused")); }
    else void read(false);
    return stop;
  }, [period, session.phase, session.request, session.showLogin]);

  const changePeriod = useCallback((next: Period) => {
    stopRef.current();
    setPeriod(next);
    setData(null);
  }, []);
  const availability = data?.availability ?? {};
  const batteryAvailable = availability.battery_applicable !== false && data?.battery?.applicable !== false;
  const battery = data?.battery ?? {};
  const minimumState = batteryAvailable && battery.minimum_soc_pct != null
    ? UI.socState(Number(battery.minimum_soc_pct)) : null;
  const warnings = [
    ...(data?.warnings ?? []),
    ...(data?.warning_codes ?? []).map(item => item.code === "OFFICIAL_REPORT_MISSING"
      ? t("warning.officialMissing")
      : item.code === "SUMMARY_MISSING" ? t("warning.summaryMissing", { days: (item.days ?? []).join(", ") }) : item.code)
  ];

  return <main>
    <PageState phase={session.phase} message={session.message} onLogin={session.login}>
      <Header page="daily" period={period} onLogout={() => { stopRef.current(); session.logout(); }} />
      <section>
        {!!(error || warnings.length) && <div className="banner" role="status">{[error, ...warnings].filter(Boolean).join("\n")}</div>}
        <div className="toolbar">
          <div className="controls">
            <PeriodNavigator period={period} onChange={changePeriod} />
            <button className="primary" type="button" disabled={busy} onClick={() => load(true)}>
              {busy ? t("common.loading") : t("common.refresh")}
            </button>
            <span>{document.hidden ? t("status.paused") : t("status.auto")}</span>
          </div>
          <span className="muted" role="status">{status}</span>
        </div>
        <div className="range-info"><span>{formatRange(period)}</span><span>{data?.checked_at ? t("status.readAt", { time: UI.stampLabel(data.checked_at, true) }) : ""}</span></div>

        <section className="analytics-section"><h2>{t("daily.energy")}</h2><div className="grid two">
          {energyCards.map(([label, metric]) => {
            const isBattery = metric.startsWith("battery_");
            const notApplicable = isBattery && !batteryAvailable;
            return <KpiCard key={metric} label={t(label)} description={t("energy.rangeDetail")}
              loading={!data} value={notApplicable ? t("common.notApplicable") : fmt(data?.energy?.[metric])}
              unit={notApplicable ? "" : "kWh"} meta={notApplicable ? t("battery.notInstalled") : ""} />;
          })}
        </div></section>

        <section className="analytics-section"><h2>{t("daily.performance")}</h2><div className="grid one">
          <KpiCard label={t("performance.self")} description={t("performance.formula")}
            loading={!data} value={fmt(data?.performance?.self_sufficiency_pct, 1)} unit="%" accent />
        </div></section>

        <section className="analytics-section"><h2>{t("daily.peaks")}</h2><div className="grid two">
          {(["pv", "load", "grid_import", "grid_export"] as const).map((metric, index) => {
            const labels = ["peak.pv", "peak.load", "peak.import", "peak.export"];
            const peak = data?.peaks?.[metric];
            return <KpiCard key={metric} label={t(labels[index])} description={t("peak.detail")}
              loading={!data} value={fmt(peak?.kw)} unit="kW" meta={UI.analyticsTimeLabel(peak?.time, period)} />;
          })}
        </div></section>

        <section className="analytics-section"><h2>{t("daily.battery")}</h2><div className="grid two">
          <KpiCard label={t("battery.reserve")} description={t("battery.reserveDetail", { value: batteryAvailable ? fmt(battery.reserve_soc_pct, 0) : "—" })}
            loading={!data} value={!batteryAvailable ? t("common.notApplicable") : battery.reserve_reached_time ? UI.analyticsTimeLabel(battery.reserve_reached_time, period) : t("battery.notReached")}
            meta={!batteryAvailable ? t("battery.notInstalled") : battery.reserve_reached_time ? `${fmt(battery.reserve_soc_pct, 0)}%` : ""} />
          <KpiCard label={t("battery.minimum")} description={t("battery.minimumDetail")}
            loading={!data} value={batteryAvailable ? fmt(battery.minimum_soc_pct, 0) : t("common.notApplicable")}
            unit={batteryAvailable && battery.minimum_soc_pct != null ? "%" : ""}
            meta={!batteryAvailable ? t("battery.notInstalled") : UI.analyticsTimeLabel(battery.minimum_soc_time, period)}
            statusClass={minimumState?.className ?? ""} />
          <KpiCard label={t("battery.peakPeriod")} description={t("battery.peakDetail")}
            loading={!data} value={fmt(data?.peak_period?.grid_import_18_21_kwh)} unit="kWh" />
        </div></section>

        <section className="analytics-section"><h2>{t("daily.quality")}</h2><div className="grid one">
          <KpiCard label={t("quality.coverage")} description={t("quality.samples", {
            observed: data?.data_quality?.raw_samples ?? "—", expected: data?.data_quality?.expected_samples ?? "—"
          })} loading={!data} value={fmt(data?.data_quality?.raw_coverage_pct, 1)} unit="%"
            progress={data?.data_quality?.raw_coverage_pct ?? null} />
        </div></section>
        <footer><span>{t("daily.footer")}</span><span>v0.6.2 · React</span></footer>
      </section>
    </PageState>
  </main>;
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");
createRoot(root).render(<Daily />);
