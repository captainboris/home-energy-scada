import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CurrentReadings } from "./components/CurrentReadings";

afterEach(() => vi.useRealTimers());

describe("Current Readings cards", () => {
  it("renders four dense entities with SOC, estimated kWh and explicit directions", () => {
    vi.useFakeTimers();
    vi.setSystemTime(10_000);
    const { container } = render(<CurrentReadings latest={{
      pv_power_kw: { t: 7000, value: 4.21 },
      load_power_kw: { t: 7000, value: 2.37 },
      battery_soc_pct: { t: 7000, value: 72 },
      battery_charge_power_kw: { t: 7000, value: 1.56 },
      battery_discharge_power_kw: { t: 7000, value: 0 },
      grid_import_power_kw: { t: 7000, value: 0 },
      grid_export_power_kw: { t: 7000, value: 0.28 }
    }} health={{ healthy: true }} />);

    expect(container.querySelectorAll(".energy-flow-card")).toHaveLength(4);
    for (const label of ["PV", "Home Load", "Battery", "Grid"]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
    expect(screen.getByText("≈ 20.2 kWh")).toBeTruthy();
    expect(screen.getByText("Charging")).toBeTruthy();
    expect(screen.getByText("1.56 kW")).toBeTruthy();
    expect(screen.getByText("Exporting")).toBeTruthy();
    expect(screen.queryByText("Updated 3s ago")).toBeNull();
    expect(container.querySelector(".battery-reading .value")?.classList.contains("soc-normal")).toBe(true);
  });

  it("shows per-reading source age only after two minutes", () => {
    vi.useFakeTimers();
    vi.setSystemTime(130_000);
    render(<CurrentReadings latest={{
      pv_power_kw: { t: 7000, value: 4.21 },
      load_power_kw: { t: 7000, value: 2.37 },
      battery_soc_pct: { t: 7000, value: 72 },
      battery_charge_power_kw: { t: 7000, value: 1.56 },
      battery_discharge_power_kw: { t: 7000, value: 0 },
      grid_import_power_kw: { t: 7000, value: 0 },
      grid_export_power_kw: { t: 7000, value: 0.28 }
    }} health={{ healthy: true }} />);

    expect(screen.getAllByText("Updated 2m ago")).toHaveLength(4);
  });

  it("does not turn missing telemetry into a synthetic zero or false Idle state", () => {
    render(<CurrentReadings latest={{}} />);
    expect(screen.getAllByText("Waiting for telemetry")).toHaveLength(3);
    expect(screen.queryByText("0.00")).toBeNull();
  });
});

describe("Current Readings scene flow animation", () => {
  it("updates directional arrows from normalized channels and stops zero, missing and stale flow", () => {
    vi.useFakeTimers(); vi.setSystemTime(10000);
    const readings = (charge: number, discharge: number, take: number, feed: number) => ({
      pv_power_kw: {t: 9000, value: 3}, load_power_kw: {t: 9000, value: 2},
      battery_soc_pct: {t: 9000, value: 75},
      battery_charge_power_kw: {t: 9000, value: charge}, battery_discharge_power_kw: {t: 9000, value: discharge},
      grid_import_power_kw: {t: 9000, value: take}, grid_export_power_kw: {t: 9000, value: feed}
    });
    const view = render(<CurrentReadings latest={readings(1, 0, 0, 2)} />);
    const direction = (kind: string) => view.container.querySelector(`[data-flow="${kind}"]`)?.getAttribute("data-direction");
    expect(direction("pv")).toBe("forward"); expect(direction("load")).toBe("forward");
    expect(direction("battery")).toBe("forward"); expect(direction("grid")).toBe("reverse");
    expect(view.container.querySelector('[data-flow="grid"] animateMotion')?.getAttribute("keyPoints")).toBe("1;0");
    view.rerender(<CurrentReadings latest={readings(0, 1, 2, 0)} />);
    expect(direction("battery")).toBe("reverse"); expect(direction("grid")).toBe("forward");
    expect(screen.getByText("Discharging")).toBeTruthy(); expect(screen.getByText("Importing")).toBeTruthy();
    view.rerender(<CurrentReadings latest={readings(0, 0, 0, 0)} />);
    expect(direction("battery")).toBe("inactive"); expect(direction("grid")).toBe("inactive");
    expect(view.container.querySelector('[data-flow="battery"] animateMotion')).toBeNull();
    view.rerender(<CurrentReadings latest={readings(1, 0, 1, 0)} health={{healthy: false}} />);
    expect(view.container.querySelectorAll("animateMotion")).toHaveLength(0);
    vi.setSystemTime(200000);
    act(() => vi.advanceTimersByTime(1000));
    view.rerender(<CurrentReadings latest={readings(1, 0, 1, 0)} />);
    expect(view.container.querySelectorAll("animateMotion")).toHaveLength(0);
    view.rerender(<CurrentReadings latest={{}} />);
    expect(view.container.querySelectorAll("animateMotion")).toHaveLength(0);
    expect(screen.queryByText("0.00")).toBeNull();
  });

  it("does not animate zero PV/load or old battery power beside a fresh SOC reading", () => {
    vi.useFakeTimers(); vi.setSystemTime(200000);
    const view = render(<CurrentReadings latest={{
      pv_power_kw: {t: 199000, value: 0}, load_power_kw: {t: 199000, value: 0},
      battery_soc_pct: {t: 199000, value: 80}, battery_charge_power_kw: {t: 1000, value: 2}
    }} />);
    expect(view.container.querySelectorAll("animateMotion")).toHaveLength(0);
    expect(screen.getByText("≈ 22.4 kWh")).toBeTruthy();
  });
});
