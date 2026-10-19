// Rendered Chromium + mock API evidence only, not iPhone/Safari hardware evidence.
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const fixture = require("./fixtures/energy-summary.json");
const output = process.env.SCADA_SMOKE_OUTPUT || path.resolve(__dirname, "../../../qa");
const base = "http://127.0.0.1:4173";
const keys = ["pv_kwh", "grid_import_kwh", "battery_discharge_kwh", "load_kwh", "grid_export_kwh", "battery_charge_kwh"];
const json = (route, body) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });

async function ribbons(page, values) {
  const positive = values.filter(value => value > 0);
  await page.waitForFunction(count => document.querySelectorAll('.energy-sankey-chart svg path[d*="C"]').length === count, positive.length);
  const heights = await page.locator('.energy-sankey-chart svg path[d*="C"]').evaluateAll(nodes => nodes.map(node => {
    const numbers = node.getAttribute("d").match(/-?\d*\.?\d+(?:e[+-]?\d+)?/gi).map(Number);
    return numbers[9] - numbers[7]; // ribbon's L endpoint minus preceding C endpoint
  }));
  const scale = heights[0] / positive[0];
  positive.forEach((value, i) => assert.ok(Math.abs(heights[i] - value * scale) < 0.02,
    `Ribbon ${i} changed the common kWh scale: ${heights[i]} vs ${value * scale}`));
  const texts = await page.locator(".energy-sankey-chart svg").textContent();
  for (const value of values) assert.ok(texts.includes(`${value.toLocaleString("en-AU", {minimumFractionDigits: 2, maximumFractionDigits: 3})} kWh`));
  return heights;
}

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const errors = [];
  const context = await browser.newContext({ viewport: { width: 1440, height: 1050 } });
  const page = await context.newPage();
  page.on("pageerror", error => errors.push(error.message));
  await page.clock.setFixedTime(new Date("2026-10-03T01:00:00+10:00"));
  await page.addInitScript(() => localStorage.setItem("home-energy-language", "en"));
  let response = structuredClone(fixture);
  let calls = 0;
  const pending = [];
  let hold = false;
  await page.route("**/api/session", route => json(route, { ok: true, last_activity: 1790953200, idle_deadline: 1790955000, idle_seconds: 1800 }));
  await page.route("**/api/activity", route => json(route, { ok: true }));
  await page.route("**/api/summary/range?*", route => { calls++; return hold ? pending.push(route) : json(route, response); });
  const url = `${base}/daily.html?view=day&date=2026-10-02`;
  await page.goto(url, { waitUntil: "networkidle" });
  await page.evaluate(() => window.HomeEnergyUI.setLanguage("en"));
  await page.locator(".energy-sankey").scrollIntoViewIfNeeded();
  const positive = await ribbons(page, keys.map(key => response.data.energy[key]));
  assert.ok((await page.locator(".energy-sankey-difference").innerText()).includes("5.00 kWh"));
  assert.ok((await page.locator(".energy-sankey-note").innerText()).includes("not a physical AC bus"));
  assert.ok((await page.locator(".energy-sankey").innerText()).includes("Hourly completeness"));
  assert.equal(calls, 1, "Sankey must not add an API request");
  const firstRibbon = page.locator('.energy-sankey-chart svg path[d*="C"]').first();
  await firstRibbon.hover();
  await page.waitForFunction(() => document.querySelector(".energy-sankey-tooltip")?.textContent.includes("50%"));
  assert.ok((await page.locator(".energy-sankey-tooltip").innerText()).includes("Source-to-destination attribution is unknown"));
  await page.locator(".energy-sankey").screenshot({ path: path.join(output, "sankey-positive-desktop.png") });

  const refresh = async () => {
    await page.locator(".toolbar button.primary:not(#period-apply)").click();
    await page.waitForFunction(() => !document.querySelector(".toolbar button.primary:not(#period-apply)").disabled);
    await page.locator(".energy-sankey").scrollIntoViewIfNeeded();
  };
  response.data.energy.load_kwh = 18;
  await refresh();
  const negative = await ribbons(page, keys.map(key => response.data.energy[key]));
  assert.ok((await page.locator(".energy-sankey-difference").innerText()).includes("-5.00 kWh"));
  await page.locator(".energy-sankey").screenshot({ path: path.join(output, "sankey-negative-desktop.png") });
  for (const width of [900, 390, 320, 1440]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.waitForFunction(() => {
      const host = document.querySelector(".energy-sankey-chart");
      const svg = host?.querySelector("svg");
      return svg && Math.abs(svg.getBoundingClientRect().width - host.getBoundingClientRect().width) < 1;
    });
    await ribbons(page, keys.map(key => response.data.energy[key]));
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), `Horizontal overflow at ${width}px`);
  }
  await page.evaluate(() => window.HomeEnergyUI.setLanguage("zh-CN"));
  await page.waitForFunction(() => document.querySelector(".energy-sankey-chart svg")?.textContent.includes("统计汇总池"));
  await page.evaluate(() => window.HomeEnergyUI.setLanguage("en"));
  response.data.energy.pv_kwh = null;
  await refresh();
  assert.equal(await page.locator(".energy-sankey-chart svg").count(), 0);
  assert.equal(await page.locator(".energy-sankey").getAttribute("data-flow-mode"), "unavailable");
  assert.ok((await page.locator(".energy-sankey-ports").innerText()).includes("18.00 kWh"));
  response.data.energy.pv_kwh = 0;
  await refresh(); await ribbons(page, keys.map(key => response.data.energy[key]));
  assert.equal(await page.locator('.energy-sankey-chart svg path[d*="C"]').count(), 5, "Zero must not become a 1px ribbon");
  for (const key of keys) response.data.energy[key] = 0;
  await refresh();
  assert.equal(await page.locator(".energy-sankey").getAttribute("data-flow-mode"), "zero");
  assert.equal(await page.locator(".energy-sankey-chart svg").count(), 0);
  response = structuredClone(fixture); response.data.energy.pv_kwh = 0.001;
  await refresh();
  assert.equal(await page.locator(".energy-sankey").getAttribute("data-flow-mode"), "proportions");
  assert.equal(await page.locator(".energy-sankey-chart svg").count(), 0);
  const tinyBar = await page.locator('[data-energy-port="pv_kwh"] .energy-sankey-bar>span').evaluate(node => parseFloat(node.style.width));
  assert.ok(Math.abs(tinyBar - 0.001 / 15 * 100) < 1e-6, "Fallback must preserve the uninflated proportion within CSS serialization precision");
  await page.locator(".energy-sankey").screenshot({ path: path.join(output, "sankey-small-value-fallback.png") });
  // Two deferred periods: old success must never replace the new graph or KPI.
  hold = true;
  await page.locator("#period-prev").click();
  await page.locator("#period-prev").click();
  await page.waitForFunction(() => document.querySelector(".energy-sankey")?.getAttribute("data-flow-mode") === "loading");
  const deadline = Date.now() + 5000;
  while (pending.length < 2 && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 20));
  assert.equal(pending.length, 2);
  const current = structuredClone(fixture);
  const query = new URL(pending[1].request().url()).searchParams;
  current.data.range.start_ms = Number(query.get("from_ms")); current.data.range.end_ms = Number(query.get("to_ms"));
  current.data.report_dates.start = current.data.report_dates.end = await page.evaluate(stamp => window.HomeEnergyUI.localInput(stamp).date, current.data.range.start_ms);
  current.data.availability.battery_install_date = "2026-09-01";
  current.data.energy.pv_kwh = 7;
  await json(pending[1], current);
  await page.waitForFunction(() => document.querySelector(".energy-sankey-chart svg")?.textContent.includes("7.00 kWh"));
  await json(pending[0], fixture);
  await page.waitForTimeout(60);
  assert.ok((await page.locator(".energy-sankey-chart svg").textContent()).includes("7.00 kWh"));
  await context.close();

  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true, deviceScaleFactor: 1 });
  const phone = await mobile.newPage();
  phone.on("pageerror", error => errors.push(error.message));
  await phone.clock.setFixedTime(new Date("2026-10-02T12:00:00+10:00"));
  await phone.route("**/api/session", route => json(route, { ok: true, last_activity: 1790906400, idle_deadline: 1790908200, idle_seconds: 1800 }));
  await phone.route("**/api/activity", route => json(route, { ok: true }));
  await phone.route("**/api/summary/range?*", route => json(route, fixture));
  await phone.goto(url, { waitUntil: "networkidle" });
  await phone.evaluate(() => window.HomeEnergyUI.setLanguage("en"));
  await phone.locator(".energy-sankey-chart").scrollIntoViewIfNeeded();
  await ribbons(phone, keys.map(key => fixture.data.energy[key]));
  assert.ok((await phone.locator(".energy-sankey-notices").innerText()).includes("Partial"));
  await phone.locator('.energy-sankey-chart svg path[d*="C"]').first().tap();
  assert.equal(await phone.locator(".energy-sankey-chart svg").evaluate(node => getComputedStyle(node).webkitTapHighlightColor), "rgba(0, 0, 0, 0)");
  await phone.waitForFunction(() => document.querySelector(".energy-sankey-tooltip")?.textContent.includes("50%"));
  assert.ok((await phone.locator(".energy-sankey-tooltip").innerText()).includes("Partial"));
  await phone.locator(".energy-sankey").screenshot({ path: path.join(output, "sankey-mobile-tooltip.png") });
  await phone.locator(".energy-sankey-chart").scrollIntoViewIfNeeded();
  const box = await phone.locator(".energy-sankey-chart").boundingBox();
  const before = await phone.evaluate(() => window.scrollY);
  const cdp = await mobile.newCDPSession(phone);
  const x = box.x + box.width / 2, y = box.y + box.height / 2;
  await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y }] });
  for (let i = 1; i <= 6; i++) await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: y - i * 20 }] });
  await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
  await phone.waitForFunction(before => window.scrollY > before + 30, before);
  assert.ok(await phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await mobile.close();
  await browser.close();
  assert.deepEqual(errors, []);
  console.log(JSON.stringify({ ok: true, commonScalePositive: positive, commonScaleNegative: negative,
    resize: true, language: true, stalePeriod: true, zeroAndMissing: true, tiny: true,
    mobileTap: true, chromiumEmulatedTouchScroll: true, realIPhoneSafari: "NOT TESTED" }));
})().catch(error => { console.error(error.stack || error); process.exit(1); });
