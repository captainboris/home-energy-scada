import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import type { HistoryData, LiveData, Period, Reading, TelemetryHealth, ZoomRange } from "./types";
import { mergeLatest, mergePointSeries } from "./data";
import { nextCursor, shouldAppendToHistorian, shouldPollCurrentReadings } from "./live";
import { REALTIME_INITIAL_LOOKBACK_MS, REALTIME_POLL_INTERVAL_MS } from "./config";
import { UI, t, useLanguage } from "./ui";
import { useSession } from "./useSession";
import { Header, PageState, formatRange } from "./components/AppChrome";
import { PeriodNavigator } from "./components/PeriodNavigator";
import { CurrentReadings } from "./components/CurrentReadings";
import { HistorianChart } from "./components/HistorianChart";
import { selectedPeriodRange } from "./zoom";

const chartGroups = [
  { id: "solar-load", titleKey: "group.solarLoad", unit: "kW", metrics: ["pv_power_kw", "load_power_kw"] },
  { id: "grid", titleKey: "group.grid", unit: "kW", metrics: ["grid_import_power_kw", "grid_export_power_kw"] },
  { id: "battery-power", titleKey: "group.batteryPower", unit: "kW", metrics: ["battery_charge_power_kw", "battery_discharge_power_kw"] },
  { id: "battery-soc", titleKey: "group.soc", unit: "%", metrics: ["battery_soc_pct"] }
];

function initialVisibility() {
  let hidden: string[] = [];
  try { hidden = JSON.parse(localStorage.getItem("home-energy-v2-hidden") || "[]"); } catch { hidden = []; }
  return Object.fromEntries(chartGroups.flatMap(group => group.metrics).map(metric => [metric, !hidden.includes(metric)]));
}

function sourceLabel(data: HistoryData | null) {
  if (!data) return "";
  const available = data.source_segments.filter(segment => segment.available);
  if (available.length > 1) return "REST 5m + Fast telemetry";
  if (available[0]?.source === "ws_fast") return `Fast telemetry · ${data.resolution_seconds < 60 ? `${data.resolution_seconds}s` : `${data.resolution_seconds / 60}m`}`;
  if (available[0]?.source === "rest_coarse") return "REST historian · coarse";
  return "REST historian · ~5m";
}

function Overview() {
  const session = useSession();
  useLanguage();
  const [period, setPeriod] = useState<Period>(() => UI.periodFromUrl());
  const [history, setHistory] = useState<HistoryData | null>(null);
  const [currentLatest, setCurrentLatest] = useState<Record<string, Reading>>({});
  const [currentHealth, setCurrentHealth] = useState<TelemetryHealth | undefined>();
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const [visibility, setVisibility] = useState<Record<string, boolean>>(initialVisibility);
  const [syncCommand, setSyncCommand] = useState<{ version: number; range: ZoomRange } | null>(null);
  const [restoreVersion, setRestoreVersion] = useState(0);
  const generation = useRef(0);
  const liveCursor = useRef<number | null>(null);
  const liveInFlight = useRef(false);
  const periodRef = useRef(period);
  periodRef.current = period;

  const loadHistory = useCallback(async (manual = false) => {
    if (session.phase !== "app") return;
    const ticket = ++generation.current;
    setBusy(true);
    setError("");
    setStatus(t("status.readingHistory"));
    const params = new URLSearchParams(UI.periodQuery(period));
    params.set("resolution", "auto");
    try {
      const body = await session.request<{ data: HistoryData }>(`/api/history/unified?${params}`);
      if (ticket !== generation.current) return;
      setHistory(body.data);
      if (body.data.last_source_timestamp != null && shouldAppendToHistorian(period, Date.now())) {
        liveCursor.current = liveCursor.current == null
          ? body.data.last_source_timestamp
          : nextCursor(liveCursor.current, body.data.last_source_timestamp);
      }
      setStatus(manual ? t("status.reloaded") : t("status.checked"));
    } catch (reason) {
      const apiError = reason as Error & { status?: number };
      if (apiError.status === 401) session.showLogin(apiError.message);
      else {
        setError(apiError.message);
        setStatus(t("status.failed"));
      }
    } finally {
      if (ticket === generation.current) setBusy(false);
    }
  }, [period, session.phase, session.request, session.showLogin]);

  useEffect(() => { loadHistory(false); }, [loadHistory]);

  useEffect(() => {
    const pop = () => setPeriod(UI.periodFromUrl());
    window.addEventListener("popstate", pop);
    return () => window.removeEventListener("popstate", pop);
  }, []);

  useEffect(() => {
    if (session.phase !== "app") return;
    let stopped = false;
    let timer: number | null = null;

    const schedule = () => {
      if (!stopped && shouldPollCurrentReadings(document.hidden)) {
        timer = window.setTimeout(poll, REALTIME_POLL_INTERVAL_MS);
      }
    };
    const poll = async () => {
      if (stopped || document.hidden || liveInFlight.current) return;
      liveInFlight.current = true;
      const since = liveCursor.current ?? Date.now() - REALTIME_INITIAL_LOOKBACK_MS;
      try {
        const body = await session.request<{ data: LiveData }>(`/api/history/live?since_ms=${since}`);
        if (stopped) return;
        liveCursor.current = nextCursor(since, body.data.through_ms);
        setCurrentLatest(previous => mergeLatest(previous, body.data.latest));
        setCurrentHealth(body.data.health);
        setHistory(previous => previous && shouldAppendToHistorian(periodRef.current, Date.now()) ? {
          ...previous,
          series: mergePointSeries(previous.series, body.data.points),
          latest: mergeLatest(previous.latest, body.data.latest),
          latest_observed_at: Object.values(mergeLatest(previous.latest, body.data.latest))
            .reduce<number | null>((latest, point) => point?.t ? Math.max(latest ?? 0, Number(point.t)) : latest, null)
            ? new Date(Object.values(mergeLatest(previous.latest, body.data.latest))
              .reduce<number>((latest, point) => Math.max(latest, Number(point?.t || 0)), 0)).toISOString()
            : previous.latest_observed_at,
          last_source_timestamp: liveCursor.current,
          telemetry_health: body.data.health,
          checked_at: body.data.checked_at
        } : previous);
        setStatus(body.data.sample_count ? t("status.liveUpdated") : t("status.liveChecked"));
      } catch (reason) {
        const apiError = reason as Error & { status?: number; code?: string };
        if (apiError.status === 401) session.showLogin(apiError.message);
        else if (apiError.code === "LIVE_CATCHUP_TOO_LONG") {
          liveCursor.current = Date.now() - REALTIME_INITIAL_LOOKBACK_MS;
          setStatus(t("status.liveResync"));
        }
        else setError(apiError.message);
      } finally {
        liveInFlight.current = false;
        schedule();
      }
    };
    const visibilityChanged = () => {
      if (timer !== null) window.clearTimeout(timer);
      timer = null;
      if (!document.hidden) poll();
      else setStatus(t("status.paused"));
    };
    document.addEventListener("visibilitychange", visibilityChanged);
    if (document.hidden) setStatus(t("status.paused"));
    else poll();
    return () => {
      stopped = true;
      if (timer !== null) window.clearTimeout(timer);
      document.removeEventListener("visibilitychange", visibilityChanged);
    };
  }, [session.phase, session.request, session.showLogin]);

  const changePeriod = useCallback((next: Period) => {
    generation.current += 1;
    setPeriod(next);
    setHistory(null);
    setSyncCommand(null);
    setRestoreVersion(value => value + 1);
  }, []);

  const setMetricVisible = useCallback((metric: string, visible: boolean) => {
    setVisibility(previous => {
      const next = { ...previous, [metric]: visible };
      try {
        localStorage.setItem("home-energy-v2-hidden", JSON.stringify(Object.keys(next).filter(key => !next[key])));
      } catch { /* local preference persistence is optional */ }
      return next;
    });
  }, []);

  const fullRange = useMemo<ZoomRange>(
    () => selectedPeriodRange(period, history?.range),
    [history?.range.key, period]
  );

  const sync = useCallback((range: ZoomRange) => {
    setSyncCommand(previous => ({ version: (previous?.version ?? 0) + 1, range }));
  }, []);
  const restore = useCallback(() => {
    setSyncCommand(null);
    setRestoreVersion(value => value + 1);
  }, []);

  return <main>
    <PageState phase={session.phase} message={session.message} onLogin={session.login}>
      <Header page="overview" period={period} onLogout={() => session.logout()} />
      <section>
        {!!(error || history?.warnings?.length) && <div className="banner" role="status">
          {[error, ...(history?.warnings ?? [])].filter(Boolean).join("\n")}
        </div>}
        <CurrentReadings latest={currentLatest} health={currentHealth} />
        <div className="toolbar">
          <div className="controls">
            <PeriodNavigator period={period} onChange={changePeriod} />
            <button className="primary" type="button" disabled={busy} onClick={() => loadHistory(true)}>
              {busy ? t("common.loading") : t("common.refresh")}
            </button>
            <span>{document.hidden ? t("status.paused") : t("status.liveAuto")}</span>
          </div>
          <span className="muted" role="status" aria-live="polite">{status}</span>
        </div>
        <div className="section-heading"><h2>{t("overview.historian")}</h2></div>
        <div className="range-info">
          <span>{formatRange(period)}</span>
          <div className="timestamps">
            <span className={`history-source${history?.telemetry_health?.healthy === false ? " is-stale" : ""}`}>
              {sourceLabel(history)}
            </span>
            <span>{history?.checked_at ? t("status.readAt", { time: UI.stampLabel(history.checked_at, true) }) : ""}</span>
          </div>
        </div>
        <div className="charts">
          {history ? chartGroups.map(group => <HistorianChart
            key={group.id}
            {...group}
            series={history.series}
            fullRange={fullRange}
            visibility={visibility}
            onVisibilityChange={setMetricVisible}
            syncCommand={syncCommand}
            restoreVersion={restoreVersion}
            onSync={sync}
            onRestore={restore}
          />) : <div className="chart-card chart-react-loading"><span className="spinner" />{t("status.readingHistory")}</div>}
        </div>
        <footer>
          <span>{t("overview.footer")}</span>
          <span>v0.6.2 · React + ECharts · {t("overview.collecting")}</span>
        </footer>
      </section>
    </PageState>
  </main>;
}

const root = document.getElementById("root");
if (!root) throw new Error("Missing #root");
createRoot(root).render(<Overview />);
