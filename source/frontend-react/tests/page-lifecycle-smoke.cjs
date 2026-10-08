// Real Chromium with mocked APIs/clock. Visibility is explicitly simulated;
// these checks do not establish real background-tab or mobile OS behaviour.
module.exports = async function pageLifecycleSmoke({ browser, mockApi, fixtureNow }) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.clock.install({ time: new Date(fixtureNow) });
  await mockApi(page);
  await page.route("**/api/logout", route => route.fulfill({status: 200, contentType: "application/json", body: "{}"}));
  await page.route("**/api/login", route => route.fulfill({status: 200, contentType: "application/json", body: JSON.stringify({
    ok: true, last_activity: Math.floor(fixtureNow / 1000), idle_deadline: Math.floor(fixtureNow / 1000) + 1800, idle_seconds: 1800
  })}));
  const summary = [];
  await page.route("**/api/summary/range?*", route => { summary.push(route); });
  const waitSummary = async count => {
    const deadline = Date.now() + 10000;
    while (summary.length < count && Date.now() < deadline) await new Promise(resolve => setTimeout(resolve, 20));
    if (summary.length !== count) throw new Error(`Expected ${count} summary requests, got ${summary.length}`);
  };
  const complete = (index, value, status = 200) => summary[index].fulfill({status, contentType: "application/json",
    body: JSON.stringify(status === 200 ? {data: {energy: {pv_kwh: value}}} : {error: {code: "UNAUTHORIZED", message: "stale session response"}})});
  const checkValue = value => page.waitForFunction(value => document.querySelector(".kpi-card .value")?.textContent.includes(value), value);
  const visible = async hidden => page.evaluate(hidden => {
    Object.defineProperty(document, "hidden", {configurable: true, value: hidden});
    document.dispatchEvent(new Event("visibilitychange"));
  }, hidden);

  await page.goto("http://127.0.0.1:4173/daily.html?view=day&date=2026-10-01", {waitUntil: "domcontentloaded"});
  await waitSummary(1);
  await page.locator("#period-prev").click(); await waitSummary(2);
  await page.locator("#period-prev").click(); await waitSummary(3);
  if (new URL(summary[0].request().url()).searchParams.get("from_ms") === new URL(summary[2].request().url()).searchParams.get("from_ms")) {
    throw new Error("Rapid period switching did not change summary query");
  }
  await complete(2, 7); await checkValue("7.00");
  await complete(0, 91); await complete(1, 0, 401);
  await page.clock.runFor(20);
  if (await page.locator(".login").count() || !(await page.locator(".kpi-card").first().innerText()).includes("7.00")) {
    throw new Error("Stale summary success/401 affected the current period");
  }
  await page.locator(".toolbar button.primary:not(#period-apply)").click(); await waitSummary(4);
  await complete(3, 8); await checkValue("8.00");
  await page.clock.runFor(60000); await waitSummary(5); await complete(4, 9); await checkValue("9.00");
  await page.clock.runFor(60000); await waitSummary(6); await complete(5, 10); await checkValue("10.00");
  await visible(true); await page.clock.runFor(180000);
  if (summary.length !== 6) throw new Error("Hidden Daily kept polling");
  await visible(false); await waitSummary(7); await complete(6, 11); await checkValue("11.00");

  await page.evaluate(() => {
    window.detachedPickerFocus = 0;
    const button = document.getElementById("period-current");
    const original = button.focus.bind(button);
    button.focus = (...args) => { if (!button.isConnected) window.detachedPickerFocus++; original(...args); };
  });
  await page.locator("#period-current").click(); await page.locator("#period-close").click();
  await page.getByRole("button", {name: /退出|Log out/}).click(); await page.waitForSelector(".login");
  await page.clock.runFor(180000);
  if (summary.length !== 7 || await page.evaluate(() => document.body.classList.contains("dialog-open") || window.detachedPickerFocus > 0)) {
    throw new Error("Logout left polling, picker scroll lock, or detached focus work");
  }
  await page.locator("#password").fill("smoke-only-password");
  await page.locator(".login button.primary").click();
  await page.waitForURL(url => url.pathname === "/" && url.searchParams.get("view") === "day");
  await page.waitForSelector(".echart canvas");
  await page.locator("#period-current").click(); await page.locator("#period-cancel").click();
  await page.clock.runFor(180);
  if (await page.evaluate(() => document.body.classList.contains("dialog-open"))) throw new Error("Rebuilt picker did not close");

  let liveCount = 0;
  const cursors = [];
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.pathname === "/api/history/live") { liveCount++; cursors.push(Number(url.searchParams.get("since_ms"))); }
  });
  await page.locator("#period-prev").click(); await page.waitForSelector(".echart canvas");
  const before = liveCount;
  await page.clock.runFor(5000);
  await page.waitForFunction(() => [...document.querySelectorAll(".energy-flow-card .value")].every(node => !node.textContent.includes("—")));
  // Flush real network/mock completion before advancing the next clock interval.
  await page.waitForTimeout(20);
  if (liveCount <= before) throw new Error("Historical period stopped Current Readings polling");
  await visible(true); const paused = liveCount; await page.clock.runFor(15000);
  if (liveCount !== paused) throw new Error("Hidden Overview kept polling");
  await visible(false); await page.waitForTimeout(20);
  if (liveCount !== paused + 1 || cursors.some((cursor, i) => i && cursor < cursors[i - 1])) {
    throw new Error("Visible Overview did not immediately resume a monotone cursor");
  }
  await page.getByRole("button", {name: /退出|Log out/}).click(); await page.waitForSelector(".login");
  const stopped = liveCount; await page.clock.runFor(15000);
  if (liveCount !== stopped) throw new Error("Logged-out Overview kept polling");
  await context.close();
  if (errors.length) throw new Error(errors.join("\n"));
};
