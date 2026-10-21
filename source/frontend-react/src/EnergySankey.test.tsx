import { StrictMode } from "react";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import fixture from "../tests/fixtures/energy-summary.json";
import type { DailyData, Period } from "./types";

const chart = vi.hoisted(() => ({ setOption: vi.fn(), dispatchAction: vi.fn(), dispose: vi.fn(), resize: vi.fn(), init: vi.fn() }));
vi.mock("echarts/core", () => ({ use: vi.fn(), init: chart.init }));
import { EnergySankey } from "./components/EnergySankey";
const period: Period = { mode: "day", anchor: "2026-10-02", startMs: fixture.data.range.start_ms,
  endMs: fixture.data.range.end_ms, fromDate: "2026-10-02", fromTime: "00:00", toDate: "2026-10-03", toTime: "00:00", label: "Oct 2" };
const body = () => structuredClone(fixture.data) as DailyData;
let resize: () => void;
const disconnect = vi.fn();
vi.stubGlobal("ResizeObserver", class { constructor(callback: () => void) { resize = callback; } observe() {} disconnect = disconnect; });
chart.init.mockReturnValue(chart);
beforeEach(() => vi.clearAllMocks());
afterEach(() => { Object.defineProperty(window.HomeEnergyUI, "language", { configurable: true, value: "en" }); });

describe("EnergySankey lifecycle and exact values", () => {
  it("reuses one instance for data/language updates and cleans resize/chart on unmount", () => {
    const view = render(<EnergySankey data={body()} period={period} />);
    expect(chart.init).toHaveBeenCalledTimes(1); expect(chart.setOption).toHaveBeenCalledTimes(1);
    const next = body(); next.energy!.pv_kwh = 12;
    view.rerender(<EnergySankey data={next} period={period} />);
    expect(chart.setOption.mock.lastCall![0].series[0].links[0].value).toBe(12);
    const calls = chart.setOption.mock.calls.length;
    act(() => { Object.defineProperty(window.HomeEnergyUI, "language", { configurable: true, value: "zh-CN" }); window.dispatchEvent(new Event("languagechange")); });
    expect(chart.setOption).toHaveBeenCalledTimes(calls + 1);
    resize(); expect(chart.resize).toHaveBeenCalledTimes(1);
    view.unmount(); expect(disconnect).toHaveBeenCalledTimes(1); expect(chart.dispose).toHaveBeenCalledTimes(1);
  });
  it.each(["loading", "missing", "zero", "intraday", "tiny"])("removes the previous graph on %s", state => {
    const view = render(<EnergySankey data={body()} period={period} />);
    const next = body();
    if (state === "missing") next.energy!.pv_kwh = null;
    if (state === "zero") for (const key of Object.keys(next.energy!)) next.energy![key] = 0;
    if (state === "tiny") next.energy!.pv_kwh = 0.001;
    view.rerender(<EnergySankey data={state === "loading" ? null : next} period={state === "intraday" ? { ...period, fromTime: "12:00" } : period} />);
    expect(screen.queryByRole("img")).toBeNull(); expect(chart.dispose).toHaveBeenCalledTimes(1);
    if (state === "tiny") expect(view.container.querySelector('[data-energy-port="pv_kwh"] small')?.textContent).toContain("0.01%");
    if (state === "missing") { expect(view.container.textContent).toContain("sankey.unavailable"); expect(view.container.textContent).toContain("5.00 kWh"); }
  });
  it("uses textContent for tooltips and includes side share, origin and quality limits", () => {
    render(<EnergySankey data={body()} period={period} />);
    const formatter = chart.setOption.mock.lastCall![0].tooltip.formatter;
    const tip = formatter({ data: { metric: "pv_kwh" } }) as HTMLElement;
    expect(tip.textContent).toContain("10.00 kWh"); expect(tip.textContent).toContain("50%");
    expect(tip.textContent).toContain("sankey.official"); expect(tip.textContent).toContain("sankey.hourlyUnknown");
    expect(tip.textContent).toContain("sankey.noAttribution"); expect(tip.childElementCount).toBe(0);
    expect(formatter({ data: { name: "pool" } })).toBe("");
  });
  it("survives StrictMode rebuild and does not leak an instance", () => {
    const view = render(<StrictMode><EnergySankey data={body()} period={period} /></StrictMode>);
    expect(chart.init).toHaveBeenCalledTimes(2); expect(chart.dispose).toHaveBeenCalledTimes(1);
    view.unmount(); expect(chart.dispose).toHaveBeenCalledTimes(2);
  });
});

it("keeps concise quality/difference information and original graph values without a duplicate port list", () => {
  const view = render(<EnergySankey data={body()} period={period} />);
  expect(view.container.querySelector(".energy-sankey-ports")).toBeNull();
  expect(view.container.querySelector(".energy-sankey-difference")?.textContent).toContain("5.00 kWh");
  expect(view.container.querySelector(".energy-sankey-notices")?.textContent).toContain("sankey.partial");
  expect(chart.setOption.mock.lastCall![0].series[0].links.map((link: {value: number}) => link.value)).toEqual([10, 5, 5, 8, 3, 4]);
  const balanced = body(); balanced.energy!.load_kwh = 13;
  view.rerender(<EnergySankey data={balanced} period={period} />);
  expect(view.container.querySelector(".energy-sankey-difference")).toBeNull();
});
