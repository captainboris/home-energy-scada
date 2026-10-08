import { act, cleanup, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HistorianChart } from "./components/HistorianChart";
import type { SeriesRow } from "./types";

const mocks = vi.hoisted(() => ({
  chart: {
    setOption: vi.fn(), getOption: vi.fn(), dispatchAction: vi.fn(), on: vi.fn(),
    getZr: () => ({ on: vi.fn() }), resize: vi.fn(), dispose: vi.fn()
  },
  observe: vi.fn(), disconnect: vi.fn()
}));
vi.mock("echarts/core", () => ({ use: vi.fn(), init: vi.fn(() => mocks.chart) }));

const fullRange = { from: 0, to: 86400000 };
const metrics = ["pv_power_kw", "load_power_kw"];
const series: SeriesRow[] = [{ metric: metrics[0], unit: "kW", points: [[1000, 1], [2000, null]] }];
const props = {
  id: "solar-load", titleKey: "group.solarLoad", unit: "kW", metrics, series, fullRange,
  visibility: {}, onVisibilityChange: vi.fn(), syncCommand: null, restoreVersion: 0,
  onSync: vi.fn(), onRestore: vi.fn()
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.stubGlobal("ResizeObserver", class {
    observe = mocks.observe;
    disconnect = mocks.disconnect;
  });
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

describe("HistorianChart options/lifecycle seam", () => {
  it("keeps a local and synchronized viewport through new data and visibility changes", () => {
    const { container, rerender } = render(<HistorianChart {...props} />);
    const card = container.querySelector(".chart-card")!;
    const selected = { from: 10000, to: 50000 };
    mocks.chart.getOption.mockReturnValue({ dataZoom: [{ startValue: selected.from, endValue: selected.to }] });
    const onZoom = mocks.chart.on.mock.calls.find(([name]) => name === "datazoom")![1];
    act(() => onZoom());
    expect(card.getAttribute("data-sync-dirty")).toBe("true");

    const updated = [{ ...series[0], points: [...series[0].points, [3000, 2] as [number, number]] }];
    rerender(<HistorianChart {...props} series={updated} visibility={{ load_power_kw: false }} />);
    const option = mocks.chart.setOption.mock.calls.at(-1)![0];
    expect(option.dataZoom[0]).toMatchObject({ startValue: selected.from, endValue: selected.to });
    expect(option.series[0].data).toBe(updated[0].points);
    expect(option.series[1].data).toEqual([]);
    expect(card.getAttribute("data-zoomed")).toBe("true");

    const syncCommand = { version: 1, range: { from: 20000, to: 40000 } };
    rerender(<HistorianChart {...props} syncCommand={syncCommand} />);
    expect(card.getAttribute("data-sync-dirty")).toBe("false");
    rerender(<HistorianChart {...props} syncCommand={syncCommand} series={updated} />);
    expect(mocks.chart.setOption.mock.calls.at(-1)![0].dataZoom[0]).toMatchObject({
      startValue: syncCommand.range.from, endValue: syncCommand.range.to
    });
    expect(card.getAttribute("data-sync-dirty")).toBe("false");

    rerender(<HistorianChart {...props} syncCommand={syncCommand} restoreVersion={1} />);
    expect(card.getAttribute("data-zoomed")).toBe("false");
    expect(mocks.chart.dispatchAction).toHaveBeenLastCalledWith(expect.objectContaining({
      type: "dataZoom", startValue: fullRange.from, endValue: fullRange.to
    }));
  });

  it("resets to a new period and cleans listeners, observer and instance on unmount", () => {
    const { container, rerender, unmount } = render(<HistorianChart {...props} />);
    const element = container.querySelector(".echart")!;
    const remove = vi.spyOn(element, "removeEventListener");
    const nextRange = { from: fullRange.to, to: fullRange.to * 2 };
    rerender(<HistorianChart {...props} fullRange={nextRange} />);
    expect(mocks.chart.setOption.mock.calls.at(-1)![0].xAxis).toMatchObject({
      min: nextRange.from, max: nextRange.to
    });
    expect(mocks.chart.dispatchAction).toHaveBeenLastCalledWith(expect.objectContaining({
      type: "dataZoom", startValue: nextRange.from, endValue: nextRange.to
    }));
    unmount();
    expect(mocks.disconnect).toHaveBeenCalledOnce();
    expect(mocks.chart.dispose).toHaveBeenCalledOnce();
    for (const name of ["pointerdown", "pointermove", "pointerup", "pointercancel", "wheel"]) {
      expect(remove).toHaveBeenCalledWith(name, expect.any(Function), true);
    }
  });
});
