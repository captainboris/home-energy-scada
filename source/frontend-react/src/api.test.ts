import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import sharedSource from "../public/shared.js?raw";

let requestJson: typeof import("./api").requestJson;
const controllers = new Set<AbortController>();
const fetchMock = vi.fn<typeof fetch>();

beforeAll(async () => {
  // Exercise the shipped dictionaries, including unknown-code fallbacks.
  window.eval(sharedSource);
  ({ requestJson } = await import("./api"));
});

beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("fetch", fetchMock.mockReset());
  window.HomeEnergyUI.setLanguage("en");
});

afterEach(async () => {
  try {
    expect(controllers.size).toBe(0);
    const signals = fetchMock.mock.calls.map(([, options]) => options?.signal);
    const aborted = signals.map(signal => signal?.aborted);
    // The real language switch also schedules jsdom storage events. Check the
    // request timers by their observable effect rather than counting all timers.
    await vi.advanceTimersByTimeAsync(65000);
    expect(signals.map(signal => signal?.aborted)).toEqual(aborted);
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

function json(body: unknown, status = 200, requestId = "header-id") {
  return new Response(JSON.stringify(body), { status, headers: { "x-request-id": requestId } });
}

describe("JSON transport contract", () => {
  it("preserves request options and response envelopes while enforcing transport defaults", async () => {
    const body = { data: { points: [[1000, null], [2000, 3]] } };
    fetchMock.mockResolvedValue(json(body));
    const caller = new AbortController();
    const path = "/api/history/unified?from=2026-10-01&resolution=auto";
    const pending = requestJson(path, controllers, {
      method: "POST", body: "{}", headers: { "X-Correlation-ID": "correlation" },
      credentials: "omit", cache: "force-cache", signal: caller.signal
    });
    const signal = fetchMock.mock.calls[0][1]?.signal;
    expect(fetchMock).toHaveBeenCalledWith(path, expect.objectContaining({
      method: "POST", body: "{}", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Correlation-ID": "correlation" }
    }));
    expect(controllers.size).toBe(1);
    expect(signal).toBe([...controllers][0].signal);
    expect(signal).not.toBe(caller.signal);
    caller.abort(); // The existing transport owns cancellation; caller signals are overridden.
    expect(signal?.aborted).toBe(false);
    await expect(pending).resolves.toEqual(body);
  });

  it("retains an explicitly supplied Content-Type", async () => {
    fetchMock.mockResolvedValue(json({ ok: true }));
    await requestJson("/api/example", controllers, { headers: { "Content-Type": "custom/type" } });
    expect(fetchMock.mock.calls[0][1]?.headers).toEqual({ "Content-Type": "custom/type" });
  });

  it.each([
    ["en", "You were logged out after 30 minutes without activity.\nRequest ID: body-id"],
    ["zh-CN", "超过30分钟没有操作，已自动退出。\nRequest ID：body-id"]
  ] as const)("localizes known errors in %s and preserves metadata", async (language, message) => {
    window.HomeEnergyUI.setLanguage(language);
    fetchMock.mockResolvedValue(json({ error: {
      code: "SESSION_IDLE", message: "server message", request_id: "body-id"
    } }, 401));
    await expect(requestJson("/api/session", controllers)).rejects.toMatchObject({
      message, status: 401, code: "SESSION_IDLE", requestId: "body-id"
    });
  });

  it.each([
    ["en", "Request failed (HTTP 503)\nRequest ID: header-id"],
    ["zh-CN", "服务器说明\nRequest ID：header-id"]
  ] as const)("preserves the unknown-code fallback in %s", async (language, message) => {
    window.HomeEnergyUI.setLanguage(language);
    fetchMock.mockResolvedValue(json({ error: { code: "UNRECOGNIZED", message: "服务器说明" } }, 503));
    await expect(requestJson("/api/example", controllers)).rejects.toMatchObject({
      message, status: 503, code: "UNRECOGNIZED", requestId: "header-id"
    });
  });

  it("uses the current language when a pending request fails, without inventing a request ID", async () => {
    let respond!: (response: Response) => void;
    fetchMock.mockImplementation(() => new Promise(resolve => { respond = resolve; }));
    const pending = requestJson("/api/example", controllers);
    window.HomeEnergyUI.setLanguage("zh-CN");
    respond(new Response(JSON.stringify({ error: { code: "UNKNOWN" } }), { status: 400 }));
    await expect(pending).rejects.toMatchObject({
      message: "读取失败（HTTP 400）", status: 400, code: "UNKNOWN", requestId: null
    });
  });

  it.each([200, 502])("wraps non-JSON responses at HTTP %s as service errors", async status => {
    fetchMock.mockResolvedValue(new Response("not JSON", {
      status, headers: { "x-request-id": "header-id" }
    }));
    await expect(requestJson("/api/example", controllers)).rejects.toMatchObject({
      message: `Unexpected service response (HTTP ${status}).`, status, requestId: "header-id"
    });
  });

  it("preserves fetch failures but wraps failures while reading the JSON body", async () => {
    const networkError = new TypeError("Failed to fetch");
    fetchMock.mockRejectedValueOnce(networkError);
    await expect(requestJson("/api/example", controllers)).rejects.toBe(networkError);
    const response = json({ ok: true });
    vi.spyOn(response, "json").mockRejectedValueOnce(new DOMException("Aborted", "AbortError"));
    fetchMock.mockResolvedValueOnce(response);
    await expect(requestJson("/api/example", controllers)).rejects.toMatchObject({
      message: "Unexpected service response (HTTP 200).", status: 200, requestId: "header-id"
    });
  });

  it("tracks requests through body parsing and removes only the completed controller", async () => {
    let finishBody!: (body: unknown) => void;
    const response = json({ ok: true });
    const parse = vi.spyOn(response, "json").mockImplementation(() => new Promise(resolve => { finishBody = resolve; }));
    fetchMock.mockResolvedValueOnce(response).mockImplementationOnce((_input, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    const first = requestJson("/api/history/unified", controllers);
    const second = requestJson("/api/history/live", controllers);
    const rejected = expect(second).rejects.toMatchObject({ name: "AbortError" });
    const [, secondController] = [...controllers];
    await Promise.resolve();
    expect(parse).toHaveBeenCalledOnce();
    expect(controllers.size).toBe(2);
    finishBody({ ok: true });
    await expect(first).resolves.toEqual({ ok: true });
    expect([...controllers]).toEqual([secondController]);
    secondController.abort();
    await rejected;
  });

  it("aborts at 65 seconds and leaves successful requests without a pending timeout", async () => {
    fetchMock.mockImplementationOnce((_input, options) => new Promise((_resolve, reject) => {
      options?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    const pending = requestJson("/api/example", controllers);
    const rejected = expect(pending).rejects.toMatchObject({ name: "AbortError" });
    const signal = fetchMock.mock.calls[0][1]?.signal;
    await vi.advanceTimersByTimeAsync(64999);
    expect(signal?.aborted).toBe(false);
    await vi.advanceTimersByTimeAsync(1);
    await rejected;
    fetchMock.mockResolvedValueOnce(json({ ok: true }));
    await requestJson("/api/example", controllers);
    const completedSignal = fetchMock.mock.calls[1][1]?.signal;
    await vi.advanceTimersByTimeAsync(65000);
    expect(completedSignal?.aborted).toBe(false);
  });
});
