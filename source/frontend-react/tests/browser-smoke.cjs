const { chromium } = require("playwright");
const fs = require("node:fs");
const path = require("node:path");

const output = path.resolve(__dirname, "../../../qa");
fs.mkdirSync(output, { recursive: true });
const start = Date.parse("2026-10-01T00:00:00+10:00");
const metrics = [
  "pv_power_kw", "load_power_kw", "grid_import_power_kw",
  "grid_export_power_kw", "battery_charge_power_kw",
  "battery_discharge_power_kw", "battery_soc_pct"
];
const units = Object.fromEntries(metrics.map(metric => [metric, metric.endsWith("pct") ? "%" : "kW"]));
const points = Object.fromEntries(metrics.map((metric, metricIndex) => [metric,
  Array.from({ length: 80 }, (_, index) => [start + index * 5000,
    metric.endsWith("pct") ? 82 - index * .01 : Math.max(0, 1.2 + metricIndex * .15 + Math.sin(index / 8))])
]));
let liveStamp = start + 80 * 5000;

function json(route, body) {
  return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
}

async function mockApi(page) {
  await page.route("**/api/session", route => json(route, {
    ok: true, last_activity: Math.floor(Date.now() / 1000), idle_deadline: Math.floor(Date.now() / 1000) + 1800, idle_seconds: 1800
  }));
  await page.route("**/api/activity", route => json(route, { ok: true }));
  await page.route("**/api/history/unified?*", route => json(route, { data: {
    source: "hybrid_historian", timezone: "Australia/Melbourne",
    range: { preset: "day", start_date: "2026-10-01", end_date: "2026-10-01",
      start_at: "2026-10-01T00:00:00+10:00", end_at: "2026-10-02T00:00:00+10:00",
      start_ms: start, end_ms: start + 86400000, key: `${start}/${start + 86400000}` },
    resolution: "5s_raw", resolution_seconds: 5, resolution_authority: "server",
    series: metrics.map(metric => ({ metric, unit: units[metric], points: points[metric] })),
    latest: Object.fromEntries(metrics.map(metric => [metric, { t: liveStamp - 5000, value: points[metric].at(-1)[1], quality: "good" }])),
    latest_observed_at: new Date(liveStamp - 5000).toISOString(), last_source_timestamp: liveStamp - 5000,
    warnings: [], collector: {}, telemetry_health: { healthy: true, state: "LIVE", connected: true },
    source_boundary: { timezone: "Australia/Melbourne", fast_telemetry_start_date: "2026-10-01",
      epoch_ms: start, before: "rest_5m", from_boundary: "ws_fast" },
    source_segments: [{ source: "ws_fast", start_ms: start, end_ms: start + 86400000, available: true, resolution_seconds: 5 }],
    checked_at: new Date().toISOString()
  }}));
  await page.route("**/api/history/live?*", route => {
    liveStamp += 5000;
    const live = metrics.map((metric, metricIndex) => ({ metric, unit: units[metric], points: [[liveStamp,
      metric.endsWith("pct") ? 81 : Math.max(0, 1.5 + metricIndex * .1)]] }));
    return json(route, { data: { source: "foxess_ws", timezone: "Australia/Melbourne", resolution: "5s_raw",
      resolution_seconds: 5, since_ms: liveStamp - 5000, through_ms: liveStamp, points: live, sample_count: 1,
      latest: Object.fromEntries(live.map(row => [row.metric, { t: liveStamp, value: row.points[0][1], quality: "good" }])),
      health: { healthy: true, state: "LIVE", connected: true, last_source_epoch_ms: liveStamp }, checked_at: new Date().toISOString() } });
  });
  await page.route("**/api/summary/range?*", route => json(route, { data: {
    energy: { pv_kwh: 24.2, load_kwh: 18.4, grid_import_kwh: 4.1, grid_export_kwh: 9.9,
      battery_charge_kwh: 8.2, battery_discharge_kwh: 7.4 },
    performance: { self_sufficiency_pct: 77.7 },
    peaks: { pv: { kw: 5.8, time: new Date(start + 12 * 3600000).toISOString() },
      load: { kw: 8.42, time: new Date(start + 18 * 3600000 + 37 * 60000).toISOString(), source: "fast_telemetry_raw" },
      grid_import: { kw: 3.1, time: new Date(start + 19 * 3600000).toISOString() },
      grid_export: { kw: 4.2, time: new Date(start + 13 * 3600000).toISOString() } },
    battery: { applicable: true, reserve_soc_pct: 40, reserve_reached_time: null,
      minimum_soc_pct: 38, minimum_soc_time: new Date(start + 6 * 3600000).toISOString() },
    peak_period: { grid_import_18_21_kwh: 2.8 },
    data_quality: { raw_coverage_pct: 99.1, raw_samples: 286, expected_samples: 288 },
    availability: { battery_applicable: true }, warnings: [], warning_codes: [], checked_at: new Date().toISOString()
  }}));
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  const desktop = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
  const page = await desktop.newPage();
  page.on("console", message => { if (message.type() === "error") errors.push(`console: ${message.text()}`); });
  page.on("pageerror", error => errors.push(`page: ${error.message}`));
  page.on("requestfailed", request => errors.push(`request: ${request.url()} ${request.failure()?.errorText}`));
  await mockApi(page);
  await page.goto("http://127.0.0.1:4173/?view=day&date=2026-10-01", { waitUntil: "networkidle" });
  await page.waitForSelector(".echart canvas");
  await page.waitForFunction(() => [...document.querySelectorAll(".energy-flow-card .value")]
    .every(node => !node.textContent.includes("—")));
  const flowText = await page.locator(".latest").innerText();
  for (const label of ["PV", "Home Load", "Battery", "Grid", "≈"]) {
    if (!flowText.includes(label)) throw new Error(`Missing Current Readings field: ${label}`);
  }
  if (await page.locator(".echart canvas").count() !== 4) throw new Error("Expected four ECharts canvases");
  const firstCard = page.locator(".chart-card[data-chart-id='solar-load']");
  if (await firstCard.getAttribute("data-base-from") !== String(start)
    || await firstCard.getAttribute("data-base-to") !== String(start + 86400000)) {
    throw new Error("Historian base axis is not the complete selected local day");
  }
  if (await page.getByRole("button", { name: /同步|Sync/ }).count() !== 0
    || await page.getByRole("button", { name: /复原|Restore/ }).count() !== 0) {
    throw new Error("Zoom toolbar must be hidden at the base viewport");
  }
  const firstChartBox = await page.locator(".echart").first().boundingBox();
  if (!firstChartBox) throw new Error("Missing first chart bounds");
  const plotLeft = firstChartBox.x + 58;
  const plotWidth = firstChartBox.width - 58 - 18;
  const plotY = firstChartBox.y + 120;
  await page.mouse.move(plotLeft + plotWidth * .75, plotY);
  await page.mouse.down();
  await page.mouse.move(plotLeft + plotWidth * (20 / 24), plotY, { steps: 8 });
  await page.mouse.up();
  await page.waitForFunction(() => document.querySelector("[data-chart-id='solar-load']")?.getAttribute("data-zoomed") === "true");
  if (await page.getByRole("button", { name: /同步|Sync/ }).count() !== 1
    || await page.getByRole("button", { name: /复原|Restore/ }).count() !== 1) {
    throw new Error("Local drag zoom did not expose Sync and Restore");
  }
  await page.getByRole("button", { name: /同步|Sync/ }).first().click();
  await page.waitForFunction(() => [...document.querySelectorAll(".chart-card[data-chart-id]")]
    .every(card => card.getAttribute("data-zoomed") === "true" && card.getAttribute("data-sync-dirty") === "false"));
  if (await page.getByRole("button", { name: /同步|Sync/ }).count() !== 0
    || await page.getByRole("button", { name: /复原|Restore/ }).count() !== 4) {
    throw new Error("Synchronized toolbar state is incorrect");
  }
  await page.locator(".echart").nth(1).hover();
  await page.mouse.wheel(0, -240);
  await page.waitForFunction(() => document.querySelector("[data-chart-id='grid']")?.getAttribute("data-sync-dirty") === "true");
  if (await page.getByRole("button", { name: /同步|Sync/ }).count() !== 1) {
    throw new Error("A local wheel zoom after Sync must make only that chart dirty");
  }
  await page.getByRole("button", { name: /复原|Restore/ }).first().click();
  await page.waitForFunction(() => [...document.querySelectorAll(".chart-card[data-chart-id]")]
    .every(card => card.getAttribute("data-zoomed") === "false"));
  if (await page.getByRole("button", { name: /同步|Sync/ }).count() !== 0
    || await page.getByRole("button", { name: /复原|Restore/ }).count() !== 0) {
    throw new Error("Global Restore did not hide every zoom action");
  }
  await page.waitForTimeout(5200);
  await page.screenshot({ path: path.join(output, "overview-desktop.png"), fullPage: true });

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
  const mobilePage = await mobile.newPage();
  mobilePage.on("pageerror", error => errors.push(`mobile page: ${error.message}`));
  await mockApi(mobilePage);
  await mobilePage.goto("http://127.0.0.1:4173/?view=day&date=2026-10-01", { waitUntil: "networkidle" });
  await mobilePage.waitForSelector(".echart canvas");
  const mobileChart = mobilePage.locator(".echart").first();
  const mobileBox = await mobileChart.boundingBox();
  if (!mobileBox) throw new Error("Missing mobile chart bounds");
  const mobileLeft = mobileBox.x + 58;
  const mobileRight = mobileBox.x + mobileBox.width - 18;
  const mobileY = mobileBox.y + 120;
  const touch = async (type, pointerId, x, y) => mobileChart.dispatchEvent(type, {
    pointerId, pointerType: "touch", isPrimary: pointerId === 1, clientX: x, clientY: y,
    bubbles: true, cancelable: true, button: 0, buttons: type === "pointerup" ? 0 : 1
  });
  await touch("pointerdown", 1, mobileLeft + 30, mobileY);
  await touch("pointerdown", 2, mobileRight - 30, mobileY);
  await touch("pointermove", 1, mobileLeft + 10, mobileY);
  await touch("pointermove", 2, mobileRight - 10, mobileY);
  await touch("pointerup", 2, mobileRight - 10, mobileY);
  await touch("pointerup", 1, mobileLeft + 10, mobileY);
  if (await mobilePage.locator("[data-chart-id='solar-load']").getAttribute("data-zoomed") !== "false") {
    throw new Error("Two-finger gesture must not zoom the chart");
  }
  await touch("pointerdown", 1, mobileLeft + 40, mobileY);
  await touch("pointermove", 1, mobileLeft + 42, mobileY + 80);
  await touch("pointerup", 1, mobileLeft + 42, mobileY + 80);
  if (await mobilePage.locator("[data-chart-id='solar-load']").getAttribute("data-zoomed") !== "false") {
    throw new Error("Vertical-dominant touch gesture must not zoom the chart");
  }
  await touch("pointerdown", 1, mobileLeft + 1, mobileY);
  await touch("pointerup", 1, mobileLeft + 1, mobileY);
  await mobilePage.waitForFunction(() => {
    const tooltip = document.querySelector(".historian-tooltip");
    return tooltip instanceof HTMLElement && tooltip.offsetWidth > 0 && tooltip.offsetHeight > 0;
  });
  const tooltipBox = await mobilePage.locator(".historian-tooltip").boundingBox();
  if (!tooltipBox) throw new Error("Tap did not open a real-point Tooltip");
  await touch("pointerdown", 1, tooltipBox.x + tooltipBox.width / 2, tooltipBox.y + tooltipBox.height / 2);
  await touch("pointerup", 1, tooltipBox.x + tooltipBox.width / 2, tooltipBox.y + tooltipBox.height / 2);
  await mobilePage.waitForFunction(() => {
    const tooltip = document.querySelector(".historian-tooltip");
    return !tooltip || !(tooltip instanceof HTMLElement) || tooltip.offsetWidth === 0 || tooltip.offsetHeight === 0;
  });
  await touch("pointerdown", 1, mobileLeft + (mobileRight - mobileLeft) * .25, mobileY);
  await touch("pointermove", 1, mobileLeft + (mobileRight - mobileLeft) * .75, mobileY + 24);
  const selection = mobilePage.locator(".zoom-selection").first();
  if (await selection.isHidden() || (await selection.textContent()) !== "") {
    throw new Error("Diagonal selection must show an overlay without range Tooltip text");
  }
  if (await mobilePage.locator(".historian-tooltip:visible").count()) {
    throw new Error("Tooltip must be suppressed during Drag-select");
  }
  await touch("pointerup", 1, mobileLeft + (mobileRight - mobileLeft) * .75, mobileY + 24);
  await mobilePage.waitForFunction(() => document.querySelector("[data-chart-id='solar-load']")?.getAttribute("data-zoomed") === "true");
  await mobilePage.getByRole("button", { name: /复原|Restore/ }).first().click();
  await mobilePage.screenshot({ path: path.join(output, "overview-mobile.png"), fullPage: true });

  const daily = await desktop.newPage();
  daily.on("pageerror", error => errors.push(`daily page: ${error.message}`));
  await mockApi(daily);
  await daily.goto("http://127.0.0.1:4173/daily.html?view=day&date=2026-10-01", { waitUntil: "networkidle" });
  await daily.waitForSelector(".kpi-card");
  if (await daily.locator(".kpi-card").count() < 10) throw new Error("Daily KPI cards did not render");
  if (!(await daily.locator("body").innerText()).includes("Home Load Peak")) throw new Error("Home Load Peak did not render");
  await daily.screenshot({ path: path.join(output, "daily-desktop.png"), fullPage: true });

  await browser.close();
  if (errors.length) throw new Error(errors.join("\n"));
  console.log(JSON.stringify({ ok: true, charts: 4, desktop: true, mobile: true, daily: true }));
})().catch(error => {
  console.error(error.stack || error.message);
  process.exit(1);
});
