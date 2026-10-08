import { cloneElement, type ReactElement } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import type { HistoryData, LiveData, Period, SeriesRow } from "./types";

const harness = vi.hoisted(() => ({ element: null as ReactElement | null, session: {} as Record<string, unknown> }));
vi.mock("react-dom/client", async importOriginal => {
  const original = await importOriginal<typeof import("react-dom/client")>();
  return { ...original, createRoot: (container: Element) => container.id === "root"
    ? { render: (element: ReactElement) => { harness.element = element; } }
    : original.createRoot(container) };
});
vi.mock("./useSession", () => ({ useSession: () => harness.session }));
vi.mock("./components/PeriodNavigator", () => ({ PeriodNavigator: ({ period, onChange }: {period: Period; onChange: (p: Period) => void}) =>
  <><button onClick={() => onChange({ ...period, startMs: -100000, endMs: -1, label: "Past" })}>Past period</button><button onClick={() => onChange(window.HomeEnergyUI.periodFromUrl())}>Current period</button></> }));
vi.mock("./components/HistorianChart", () => ({ HistorianChart: ({ id, series }: {id: string; series: SeriesRow[]}) =>
  <pre data-testid={id}>{JSON.stringify(series)}</pre> }));
let daily: ReactElement;
let overview: ReactElement;
const period: Period = { mode: "day", anchor: "2026-10-02", startMs: 0, endMs: 1000000,
  fromDate: "2026-10-02", fromTime: "00:00", toDate: "2026-10-03", toTime: "00:00", label: "Today" };
function deferred() {
  let resolve!: (value: unknown) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const pending: Array<ReturnType<typeof deferred> & { path: string }> = [];
const request = vi.fn((path: string) => { const next = { ...deferred(), path }; pending.push(next); return next.promise; });
const showLogin = vi.fn();
function session(phase = "app", transport = request) {
  harness.session = { phase, request: transport, showLogin, message: "", login: vi.fn(), logout: vi.fn() };
}
function history(points: SeriesRow["points"] = [[100, 1]], start = 0, end = 1000000): {data: HistoryData} {
  return { data: { source: "unified", timezone: "Australia/Melbourne", range: {
    preset: "day", start_date: "2026-10-02", end_date: "2026-10-02", start_at: "", end_at: "", start_ms: start, end_ms: end, key: `${start}-${end}` },
    series: [{ metric: "pv_power_kw", unit: "kW", points }], latest: {}, source_segments: [],
    resolution: "auto", resolution_seconds: 5, resolution_authority: "server", checked_at: "snapshot",
    last_source_timestamp: 100, source_boundary: {timezone: "Australia/Melbourne", fast_telemetry_start_date: "", epoch_ms: 0, before: "", from_boundary: ""} } };
}
function live(points: SeriesRow["points"] = [[200, 2]], through = 200): {data: LiveData} {
  return { data: { source: "ws_fast", timezone: "Australia/Melbourne", resolution: "5s", resolution_seconds: 5,
    since_ms: 0, through_ms: through, points: [{ metric: "pv_power_kw", unit: "kW", points }],
    latest: { pv_power_kw: { t: through, value: 2 } }, health: { healthy: true }, checked_at: "live", sample_count: points.length } };
}
const dailyBody = (value: number) => ({data: {energy: {pv_kwh: value}}});
async function settle(index: number, body: unknown, failure = false) {
  await act(async () => failure ? pending[index].reject(body) : pending[index].resolve(body));
}
async function tick(ms: number) { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); }
function hidden(value: boolean) {
  Object.defineProperty(document, "hidden", { configurable: true, value });
  fireEvent(document, new Event("visibilitychange"));
}
const busy = () => (document.querySelector("button.primary") as HTMLButtonElement).disabled;
const chart = () => JSON.parse(screen.getByTestId("solar-load").textContent || "[]") as SeriesRow[];
beforeAll(async () => {
  const root = document.createElement("div"); root.id = "root"; document.body.append(root);
  await import("./daily"); daily = harness.element!;
  await import("./overview"); overview = harness.element!;
  root.remove();
});
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(10000);
  pending.length = 0; request.mockClear(); showLogin.mockClear(); session();
  window.HomeEnergyUI.periodFromUrl = () => ({...period});
  window.HomeEnergyUI.periodQuery = p => ({from_ms: String(p.startMs), to_ms: String(p.endMs)});
  Object.defineProperty(document, "hidden", { configurable: true, value: false });
});
afterEach(() => { vi.useRealTimers(); });
for (const [name, element, body] of [
  ["Daily", () => daily, dailyBody(91)], ["Overview", () => overview, history([[100, 91]])]
] as const) {
  describe(`${name} request validity`, () => {
    it.each(["success", "error", "401"])("ignores stale %s and finally after period replacement", async outcome => {
      render(element()); fireEvent.click(screen.getByText("Past period"));
      const newer = pending.findIndex((p, i) => i > 0 && p.path.includes("from_ms=-100000"));
      await settle(0, outcome === "success" ? body : Object.assign(new Error("old failure"), {status: outcome === "401" ? 401 : 500}), outcome !== "success");
      expect(showLogin).not.toHaveBeenCalled(); expect(document.body.textContent).not.toContain("old failure");
      expect(busy()).toBe(true); expect(document.querySelector(".toolbar .muted")?.textContent).toMatch(/reading/);
      await settle(newer, name === "Daily" ? dailyBody(7) : history([[-20, 7]], -100000, -1));
      expect(busy()).toBe(false); expect(document.body.textContent).not.toContain("91.00");
      if (name === "Overview") expect(chart()[0].points).toEqual([[-20, 7]]);
    });
    it("invalidates a replaced request owner even for the same period", async () => {
      const view = render(element()); const replacement = vi.fn(request.getMockImplementation()!);
      session("app", replacement); view.rerender(cloneElement(element()));
      await settle(0, Object.assign(new Error("old 401"), {status: 401}), true);
      expect(showLogin).not.toHaveBeenCalled(); expect(busy()).toBe(true);
    });
    it.each(["success", "error", "401"])("old session %s cannot affect the next session", async outcome => {
      const view = render(element()); session("login"); view.rerender(cloneElement(element())); session(); view.rerender(cloneElement(element()));
      await settle(0, outcome === "success" ? body : Object.assign(new Error("old session"), {status: outcome === "401" ? 401 : 500}), outcome !== "success");
      expect(showLogin).not.toHaveBeenCalled(); expect(busy()).toBe(true); expect(document.body.textContent).not.toContain("old session");
      expect(document.body.textContent).not.toContain(name === "Daily" ? "91.00" : '[[100,91]]');
    });
    it("ignores a late success after the newer period is already displayed", async () => {
      render(element()); fireEvent.click(screen.getByText("Past period"));
      const newer = pending.findIndex(p => p.path.includes("from_ms=-100000"));
      await settle(newer, name === "Daily" ? dailyBody(7) : history([[-20, 7]], -100000, -1));
      await settle(0, body);
      expect(busy()).toBe(false);
      if (name === "Daily") { expect(document.body.textContent).toContain("7.00"); expect(document.body.textContent).not.toContain("91.00"); }
      else expect(chart()[0].points).toEqual([[-20, 7]]);
    });
    it("logout immediately invalidates pending responses", async () => {
      render(element()); fireEvent.click(screen.getByText("common.logout"));
      await settle(0, Object.assign(new Error("after logout"), {status: 401}), true);
      expect(showLogin).not.toHaveBeenCalled();
      const calls = request.mock.calls.length; await tick(120000); expect(request).toHaveBeenCalledTimes(calls);
    });
    it("preserves current-session 401 login handling", async () => {
      render(element()); await settle(0, Object.assign(new Error("current 401"), {status: 401}), true);
      expect(showLogin).toHaveBeenCalledWith("current 401");
    });
    it("unmount invalidates pending 401 and leaves no page timer", async () => {
      const view = render(element()); view.unmount(); await settle(0, Object.assign(new Error("unmounted"), {status: 401}), true);
      expect(showLogin).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
    });
  });
}
describe("Daily completion-based polling", () => {
  it("does not overlap and repeats 60 seconds after success or failure", async () => {
    render(daily); await tick(60000); expect(request).toHaveBeenCalledTimes(1);
    await settle(0, dailyBody(1)); await tick(59999); expect(request).toHaveBeenCalledTimes(1);
    await tick(1); expect(request).toHaveBeenCalledTimes(2);
    await settle(1, new Error("temporary"), true); await tick(60000); expect(request).toHaveBeenCalledTimes(3);
    await settle(2, dailyBody(3)); expect(document.body.textContent).toContain("3.00");
  });
  it("manual refresh replaces the next timer rather than duplicating it", async () => {
    render(daily); await settle(0, dailyBody(1)); await tick(30000);
    fireEvent.click(screen.getByText("common.refresh")); await settle(1, dailyBody(2));
    await tick(30000); expect(request).toHaveBeenCalledTimes(2);
    await tick(30000); expect(request).toHaveBeenCalledTimes(3);
  });
  it("pauses while hidden; visible checks immediately and coalesces an in-flight check", async () => {
    const view = render(daily); await settle(0, dailyBody(1)); hidden(true); await tick(180000); expect(request).toHaveBeenCalledTimes(1);
    hidden(false); expect(request).toHaveBeenCalledTimes(2); hidden(true); hidden(false); expect(request).toHaveBeenCalledTimes(2);
    await settle(1, dailyBody(2)); expect(request).toHaveBeenCalledTimes(3);
    await settle(2, dailyBody(3)); view.unmount(); await tick(180000); expect(request).toHaveBeenCalledTimes(3);
  });
  it("does not start new polling when mounted hidden or after logout", async () => {
    hidden(true); const view = render(daily); expect(request).not.toHaveBeenCalled(); hidden(false); expect(request).toHaveBeenCalledTimes(1);
    await settle(0, dailyBody(1)); session("login"); view.rerender(cloneElement(daily)); await tick(180000); expect(request).toHaveBeenCalledTimes(1);
  });
});
describe("Overview snapshot/live handoff", () => {
  it("retains only accepted live points during the pending load, with live winning overlaps", async () => {
    render(overview); await settle(1, live([[-1, 90], [100, 9], [200, null], [1000000, 99]], 200));
    await settle(0, history([[100, 1], [300, 3]])); expect(chart()[0].points).toEqual([[100, 9], [200, null], [300, 3]]);
    fireEvent.click(screen.getByText("common.refresh")); await settle(2, history([[300, 4]]));
    expect(chart()[0].points).toEqual([[300, 4]]);
  });
  it("discards the old period journal without resetting the live cursor", async () => {
    render(overview); await settle(1, live([[200, 2]], 200)); fireEvent.click(screen.getByText("Past period"));
    await settle(2, history([[-20, 4]], -100000, -1)); await settle(0, history([[100, 1]]));
    expect(chart()[0].points).toEqual([[-20, 4]]);
    await tick(5000); expect(pending[3].path).toBe("/api/history/live?since_ms=200");
  });
  it("does not lower a cursor advanced by a snapshot while a live request was pending", async () => {
    render(overview); const snapshot = history(); snapshot.data.last_source_timestamp = 500;
    await settle(0, snapshot); await settle(1, live([[200, 2]], 200));
    await tick(5000); expect(pending[2].path).toBe("/api/history/live?since_ms=500");
  });
  it("accumulates multiple live batches; a later snapshot watermark cannot discard overlaps", async () => {
    render(overview); await settle(1, live([[100, 0], [200, 2]], 200));
    await tick(5000); await settle(2, live([[200, 9], [300, null]], 300));
    const snapshot = history([[100, 8], [200, 8], [400, 4]]); snapshot.data.last_source_timestamp = 400;
    await settle(0, snapshot);
    expect(chart()[0].points).toEqual([[100, 0], [200, 9], [300, null], [400, 4]]);
  });
  it("history latest never replaces Current Readings", async () => {
    render(overview); await settle(1, live());
    const snapshot = history(); snapshot.data.latest = {pv_power_kw: {t: 900, value: 91}};
    await settle(0, snapshot);
    expect(document.querySelector(".latest")?.textContent).toContain("2.0");
    expect(document.querySelector(".latest")?.textContent).not.toContain("91.0");
  });
  it("browser back invalidates history through the same period boundary", async () => {
    render(overview); window.HomeEnergyUI.periodFromUrl = () => ({...period, startMs: -100000, endMs: -1});
    fireEvent(window, new PopStateEvent("popstate"));
    await settle(0, new Error("old back response"), true);
    expect(document.body.textContent).not.toContain("old back response"); expect(busy()).toBe(true);
  });
  it.each(["success", "error", "401", "catchup"])("ignores unmounted live %s without rescheduling", async outcome => {
    const view = render(overview); view.unmount();
    await settle(1, outcome === "success" ? live() : Object.assign(new Error("old live"), {status: outcome === "401" ? 401 : 500, code: outcome === "catchup" ? "LIVE_CATCHUP_TOO_LONG" : "ERROR"}), outcome !== "success");
    expect(showLogin).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
  });
  it("new-session polling is independent of an old pending poll and stale errors", async () => {
    const view = render(overview); session("login"); view.rerender(cloneElement(overview)); session(); view.rerender(cloneElement(overview));
    expect(pending.filter(p => p.path.includes("/live?")).length).toBe(2);
    await settle(1, Object.assign(new Error("old live 401"), {status: 401}), true); expect(showLogin).not.toHaveBeenCalled();
    await settle(3, live()); await tick(5000); expect(pending.filter(p => p.path.includes("/live?")).length).toBe(3);
  });
});

describe("Overview visibility scheduling", () => {
  it("pauses new polls and performs one immediate check after an in-flight visible resume", async () => {
    const view = render(overview); await settle(0, history()); await settle(1, live());
    hidden(true); await tick(15000); expect(pending.filter(p => p.path.includes("/live?")).length).toBe(1);
    hidden(false); expect(pending.filter(p => p.path.includes("/live?")).length).toBe(2);
    hidden(true); hidden(false); hidden(true); hidden(false);
    expect(pending.filter(p => p.path.includes("/live?")).length).toBe(2);
    await settle(2, live([[300, 3]], 300)); expect(pending.filter(p => p.path.includes("/live?")).length).toBe(3);
    await settle(3, live([[400, 4]], 400)); view.unmount(); await tick(15000);
    expect(pending.filter(p => p.path.includes("/live?")).length).toBe(3);
  });
  it("a current live 401 invalidates pending history and stops polling", async () => {
    render(overview); await settle(1, Object.assign(new Error("live session expired"), {status: 401}), true);
    expect(showLogin).toHaveBeenCalledWith("live session expired");
    await settle(0, history([[100, 91]]));
    expect(document.body.textContent).not.toContain('[[100,91]]');
    await tick(15000); expect(request).toHaveBeenCalledTimes(2);
  });
});
