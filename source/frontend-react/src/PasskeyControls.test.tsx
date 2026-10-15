import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";
import sharedSource from "../public/shared.js?raw";
let PasskeyLogin: typeof import("./components/PasskeyControls").PasskeyLogin;
let PasskeyManager: typeof import("./components/PasskeyControls").PasskeyManager;
beforeAll(async () => {window.eval(sharedSource); window.HomeEnergyUI.setLanguage("en");
  ({PasskeyLogin, PasskeyManager} = await import("./components/PasskeyControls"));});
beforeEach(() => {
  vi.stubGlobal("isSecureContext", true); vi.stubGlobal("PublicKeyCredential", class {});
  Object.defineProperty(navigator, "credentials", {configurable: true, value: {get: vi.fn(), create: vi.fn()}});
});
afterEach(() => {cleanup(); vi.unstubAllGlobals();});
const options = {challenge_id: "id", publicKey: {challenge: "AQI"}};
describe("Passkey UI", () => {
  it("requires a second explicit click to start browser verification", async () => {
    const complete = vi.fn().mockResolvedValue(undefined);
    render(<PasskeyLogin prepare={vi.fn().mockResolvedValue(options)} complete={complete} disabled={false} />);
    fireEvent.click(screen.getByText("Sign in with a passkey"));
    await screen.findByText("Continue verification"); expect(complete).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Continue verification"));
    await waitFor(() => expect(complete).toHaveBeenCalledWith(options, "login"));
  });
  it("cancelled ceremony retains recovery advice and can retry", async () => {
    render(<PasskeyLogin prepare={vi.fn().mockResolvedValue(options)} complete={vi.fn().mockRejectedValue(new DOMException("cancel", "NotAllowedError"))} disabled={false} />);
    fireEvent.click(screen.getByText("Sign in with a passkey")); fireEvent.click(await screen.findByText("Continue verification"));
    await screen.findByText(/Verification cancelled/); expect(screen.getByText(/Password login remains available/)).toBeTruthy();
    expect(screen.getByText("Sign in with a passkey")).toBeTruthy();
  });
  it("unsupported browsers retain password fallback", () => {
    vi.stubGlobal("PublicKeyCredential", undefined);
    render(<PasskeyLogin prepare={vi.fn()} complete={vi.fn()} disabled={false} />);
    expect(screen.getByText(/Passkeys are unavailable/)).toBeTruthy(); expect(screen.queryByRole("button")).toBeNull();
  });
  it("lists multiple keys and sends a separately authorized revoke", async () => {
    const request = vi.fn().mockResolvedValueOnce({credentials: [{key: "one", label: "Phone", revoked: false}, {key: "two", label: "Mac", revoked: false}]}).mockResolvedValueOnce({ok: true});
    render(<PasskeyManager request={request} complete={vi.fn()} showLogin={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Administrator grant"), {target: {value: "grant"}});
    fireEvent.click(screen.getByText("List passkeys")); await screen.findByText(/Phone/); expect(screen.getByText(/Mac/)).toBeTruthy();
    fireEvent.click(screen.getAllByRole("button", {name: "Revoke"})[0]);
    await waitFor(() => expect(request).toHaveBeenLastCalledWith("/api/passkey/manage", {method: "POST", body: JSON.stringify({operation: "revoke", permission: "grant", key: "one"})}));
    await waitFor(() => expect((screen.getByLabelText("Administrator grant") as HTMLInputElement).value).toBe(""));
  });
  it("registration needs a grant and label, then explicit browser confirmation", async () => {
    const complete = vi.fn().mockResolvedValue(undefined);
    render(<PasskeyManager request={vi.fn().mockResolvedValue(options)} complete={complete} showLogin={vi.fn()} />);
    expect((screen.getByText("Prepare registration") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Administrator grant"), {target: {value: "grant"}});
    fireEvent.change(screen.getByLabelText("Passkey name"), {target: {value: "Phone"}});
    fireEvent.click(screen.getByText("Prepare registration")); await screen.findByText("Continue verification"); expect(complete).not.toHaveBeenCalled();
    expect((screen.getByLabelText("Administrator grant") as HTMLInputElement).value).toBe("");
    fireEvent.click(screen.getByText("Continue verification")); await screen.findByText("Passkey registered.");
    expect(complete).toHaveBeenCalledWith(options, "register", "Phone");
  });
  it("401 returns to login; grant denial stays an operation error", async () => {
    const showLogin = vi.fn(), request = vi.fn().mockRejectedValue(Object.assign(new Error("Denied"), {status: 403}));
    render(<PasskeyManager request={request} complete={vi.fn()} showLogin={showLogin} />);
    fireEvent.change(screen.getByLabelText("Administrator grant"), {target: {value: "grant"}});
    fireEvent.click(screen.getByText("List passkeys")); await screen.findByText("Denied"); expect(showLogin).not.toHaveBeenCalled();
    request.mockRejectedValue(Object.assign(new Error("Expired"), {status: 401}));
    fireEvent.click(screen.getByText("List passkeys")); await waitFor(() => expect(showLogin).toHaveBeenCalledWith("Expired"));
  });
});
