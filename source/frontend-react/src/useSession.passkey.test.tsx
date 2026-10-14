import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import sharedSource from "../public/shared.js?raw";
const mocks = vi.hoisted(() => ({credential: vi.fn(), replace: vi.fn()}));
vi.mock("./passkey", () => ({browserCredential: mocks.credential, credentialJson: (value: unknown) => value}));
vi.mock("./navigation", () => ({replaceLoginLanding: mocks.replace}));
let useSession: typeof import("./useSession").useSession;
const fetchMock = vi.fn<typeof fetch>();
const options = {challenge_id: "id", publicKey: {challenge: "AQI"}};
const payload = {ok: true, last_activity: 1800000000, idle_deadline: 1800001800, idle_seconds: 1800};
beforeAll(async () => {window.eval(sharedSource); ({useSession} = await import("./useSession"));});
beforeEach(() => {
  mocks.credential.mockReset(); mocks.replace.mockReset(); fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({error: {code: "SESSION_TOKEN_MISSING"}}), {status: 401}));
});
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
describe("Passkey session owner", () => {
  it("accepts only server success and uses the same Melbourne Today landing as password login", async () => {
    const {result} = renderHook(() => useSession()); await waitFor(() => expect(result.current.phase).toBe("login"));
    mocks.credential.mockResolvedValue({signed: true}); fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(payload)));
    await act(() => result.current.completePasskey(options, "login"));
    expect(result.current.phase).toBe("app"); expect(mocks.replace).toHaveBeenCalledWith(window.HomeEnergyUI.todayString());
    expect(JSON.parse(String(fetchMock.mock.calls[1][1]?.body))).toMatchObject({challenge_id: "id", credential: {signed: true}});
  });
  it("a browser credential alone cannot establish a session when server verification fails", async () => {
    const {result} = renderHook(() => useSession()); await waitFor(() => expect(result.current.phase).toBe("login"));
    mocks.credential.mockResolvedValue({signed: true}); fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({error: {code: "PASSKEY_INVALID"}}), {status: 401}));
    await act(async () => {await expect(result.current.completePasskey(options, "login")).rejects.toMatchObject({status: 401});});
    expect(result.current.phase).toBe("login"); expect(mocks.replace).not.toHaveBeenCalled();
  });
  it("an existing-session deep link does not navigate or start WebAuthn", async () => {
    fetchMock.mockReset().mockResolvedValueOnce(new Response(JSON.stringify(payload)));
    const {result} = renderHook(() => useSession()); await waitFor(() => expect(result.current.phase).toBe("app"));
    expect(mocks.replace).not.toHaveBeenCalled(); expect(mocks.credential).not.toHaveBeenCalled();
  });
  it.each(["showLogin", "unmount", "otherTab"])("cancels the browser ceremony on %s and never accepts its late result", async action => {
    fetchMock.mockReset().mockResolvedValueOnce(new Response(JSON.stringify(payload)));
    const {result, unmount} = renderHook(() => useSession()); await waitFor(() => expect(result.current.phase).toBe("app"));
    let resolve!: (value: unknown) => void;
    mocks.credential.mockImplementation(() => new Promise(done => {resolve = done;}));
    const pending = result.current.completePasskey(options, "login");
    const rejection = expect(pending).rejects.toMatchObject({name: "AbortError"});
    const signal = mocks.credential.mock.calls[0][2] as AbortSignal;
    act(() => {if (action === "unmount") unmount(); else if (action === "showLogin") result.current.showLogin();
      else window.dispatchEvent(new StorageEvent("storage", {key: window.HomeEnergyUI.LOGOUT_KEY, newValue: String(Date.now())}));});
    expect(signal.aborted).toBe(true); await act(async () => {resolve({signed: true}); await rejection;});
    expect(fetchMock).toHaveBeenCalledTimes(1); expect(mocks.replace).not.toHaveBeenCalled();
  });
  it("ignores a late verify response after the session is ended", async () => {
    const {result} = renderHook(() => useSession()); await waitFor(() => expect(result.current.phase).toBe("login"));
    mocks.credential.mockResolvedValue({signed: true});
    let resolve!: (value: Response) => void; fetchMock.mockImplementationOnce(() => new Promise(done => {resolve = done;}));
    const pending = result.current.completePasskey(options, "login"); const rejection = expect(pending).rejects.toMatchObject({name: "AbortError"});
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2)); act(() => result.current.showLogin());
    await act(async () => {resolve(new Response(JSON.stringify(payload))); await rejection;});
    expect(result.current.phase).toBe("login"); expect(mocks.replace).not.toHaveBeenCalled();
  });
  it("password fallback succeeds and ends an outstanding passkey ceremony", async () => {
    const {result} = renderHook(() => useSession()); await waitFor(() => expect(result.current.phase).toBe("login"));
    let resolve!: (value: unknown) => void; mocks.credential.mockImplementation(() => new Promise(done => {resolve = done;}));
    const pending = result.current.completePasskey(options, "login"); const rejection = expect(pending).rejects.toMatchObject({name: "AbortError"});
    fetchMock.mockResolvedValueOnce(new Response(JSON.stringify(payload)));
    await act(() => result.current.login("password"));
    await act(async () => {resolve({signed: true}); await rejection;});
    expect(result.current.phase).toBe("app"); expect(mocks.replace).toHaveBeenCalledTimes(1);
  });
});
