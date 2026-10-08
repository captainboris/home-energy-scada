import { StrictMode } from "react";
import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, expect, it, vi } from "vitest";
import sharedSource from "../public/shared.js?raw";
import { PeriodNavigator } from "./components/PeriodNavigator";
import type { Period } from "./types";

let period: Period;
beforeAll(() => { window.eval(sharedSource); });
beforeEach(() => {
  vi.useFakeTimers(); vi.setSystemTime(new Date("2026-10-02T12:00:00Z"));
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  period = window.HomeEnergyUI.periodFromUrl();
});
afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.restoreAllMocks(); document.body.classList.remove("dialog-open"); });

it("React unmount releases the scroll lock and cancels close animation/focus", async () => {
  const view = render(<PeriodNavigator period={period} onChange={vi.fn()} />);
  const button = document.getElementById("period-current")!;
  const focus = vi.spyOn(button, "focus");
  fireEvent.click(button); expect(document.body.classList.contains("dialog-open")).toBe(true);
  fireEvent.keyDown(document, { key: "Escape" });
  view.unmount(); expect(document.body.classList.contains("dialog-open")).toBe(false);
  await vi.advanceTimersByTimeAsync(1000);
  expect(focus).not.toHaveBeenCalled(); expect(vi.getTimerCount()).toBe(0);
});

it("destroy is idempotent, removes owned listeners and cannot reopen or schedule work", async () => {
  // Direct compatibility consumers must explicitly destroy their instance.
  document.body.innerHTML = '<button id="period-prev"></button><button id="period-current"></button><button id="period-next"></button><button id="period-close"></button><button id="period-cancel"></button><button id="period-apply"></button><div id="period-overlay" hidden><div id="period-tabs"></div><div id="period-body"></div><span id="period-error"></span></div>';
  const overlay = document.getElementById("period-overlay")!;
  const overlayAdd = vi.spyOn(overlay, "addEventListener");
  const overlayRemove = vi.spyOn(overlay, "removeEventListener");
  const documentAdd = vi.spyOn(document, "addEventListener");
  const windowAdd = vi.spyOn(window, "addEventListener");
  const documentRemove = vi.spyOn(document, "removeEventListener");
  const windowRemove = vi.spyOn(window, "removeEventListener");
  const picker = new window.HomeEnergyUI.PeriodNavigator(period, vi.fn()) as InstanceType<typeof window.HomeEnergyUI.PeriodNavigator> & {destroy(): void; open(): void; close(): void};
  picker.open(); picker.close(); picker.destroy(); picker.destroy();
  for (const [event, handler] of overlayAdd.mock.calls) expect(overlayRemove).toHaveBeenCalledWith(event, handler);
  for (const [event, handler] of documentAdd.mock.calls.filter(([event]) => event === "keydown")) expect(documentRemove).toHaveBeenCalledWith(event, handler);
  for (const [event, handler] of windowAdd.mock.calls.filter(([event]) => event === "languagechange")) expect(windowRemove).toHaveBeenCalledWith(event, handler);
  fireEvent.click(document.getElementById("period-current")!); picker.open(); picker.close();
  fireEvent.keyDown(document, {key: "Escape"}); fireEvent(window, new Event("languagechange"));
  await vi.advanceTimersByTimeAsync(1000);
  expect(overlay.hidden).toBe(true); expect(vi.getTimerCount()).toBe(0);
  expect(document.body.classList.contains("dialog-open")).toBe(false);
  document.body.innerHTML = ""; vi.restoreAllMocks();
});

it("StrictMode rebuild owns one working picker and teardown removes its handlers", async () => {
  const onChange = vi.fn();
  const view = render(<StrictMode><PeriodNavigator period={period} onChange={onChange} /></StrictMode>);
  fireEvent.click(document.getElementById("period-current")!);
  fireEvent.click(document.getElementById("period-apply")!);
  expect(onChange).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(180);
  expect(document.body.classList.contains("dialog-open")).toBe(false);
  fireEvent.click(document.getElementById("period-current")!);
  const oldButton = document.getElementById("period-current")!;
  view.unmount(); fireEvent.click(oldButton); fireEvent(window, new Event("languagechange"));
  expect(document.body.classList.contains("dialog-open")).toBe(false);
  await vi.advanceTimersByTimeAsync(1000);
  expect(vi.getTimerCount()).toBe(0);
});
