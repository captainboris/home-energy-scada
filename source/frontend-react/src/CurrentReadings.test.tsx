import { render, screen } from "@testing-library/react";
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
    expect(screen.getAllByText("Updated 3s ago")).toHaveLength(4);
    expect(container.querySelector(".battery-reading .value")?.classList.contains("soc-normal")).toBe(true);
  });

  it("does not turn missing telemetry into a synthetic zero or false Idle state", () => {
    render(<CurrentReadings latest={{}} />);
    expect(screen.getAllByText("Waiting for telemetry")).toHaveLength(3);
    expect(screen.queryByText("0.00")).toBeNull();
  });
});
