import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import sharedSource from "../public/shared.js?raw";

let useSession: typeof import("./useSession").useSession;
const fetchMock = vi.fn<typeof fetch>();

beforeAll(async () => {
  window.eval(sharedSource);
  ({ useSession } = await import("./useSession"));
});

beforeEach(() => {
  window.HomeEnergyUI.setLanguage("en");
  vi.stubGlobal("fetch", fetchMock.mockReset());
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
    ok: true, last_activity: Date.now() / 1000, idle_deadline: Date.now() / 1000 + 1800, idle_seconds: 1800
  })));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("session transport seam", () => {
  it("keeps request stable and leaves a data-request 401 to its caller", async () => {
    const { result, rerender } = renderHook(() => useSession());
    const request = result.current.request;
    await waitFor(() => expect(result.current.phase).toBe("app"));
    rerender();
    expect(result.current.request).toBe(request);
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({
      error: { code: "SESSION_IDLE", request_id: "request-id" }
    }), { status: 401 }));
    await expect(request("/api/history/live")).rejects.toMatchObject({
      status: 401, code: "SESSION_IDLE", requestId: "request-id"
    });
    expect(result.current.phase).toBe("app");
  });

  it.each(["showLogin", "unmount"] as const)("cancels in-flight requests on %s", async action => {
    const { result, unmount } = renderHook(() => useSession());
    await waitFor(() => expect(result.current.phase).toBe("app"));
    const signals: AbortSignal[] = [];
    fetchMock.mockImplementation((_input, options) => new Promise((_resolve, reject) => {
      const signal = options!.signal!;
      signals.push(signal);
      signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    const first = expect(result.current.request("/api/history/unified")).rejects.toMatchObject({ name: "AbortError" });
    const second = expect(result.current.request("/api/history/live")).rejects.toMatchObject({ name: "AbortError" });
    expect(signals).toHaveLength(2);
    expect(signals[0]).not.toBe(signals[1]);
    act(() => action === "showLogin" ? result.current.showLogin("Session ended") : unmount());
    await Promise.all([first, second]);
    expect(signals.every(signal => signal.aborted)).toBe(true);
    if (action === "showLogin") {
      expect(result.current.phase).toBe("login");
      expect(result.current.message).toBe("Session ended");
    }
  });
});
