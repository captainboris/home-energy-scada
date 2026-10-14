import { afterEach, describe, expect, it, vi } from "vitest";
import { browserCredential, credentialJson, decodeBase64url, passkeySupported } from "./passkey";
afterEach(() => vi.unstubAllGlobals());
describe("WebAuthn browser adapter", () => {
  it("detects capability and preserves password fallback", () => {
    vi.stubGlobal("PublicKeyCredential", undefined); expect(passkeySupported()).toBeFalsy();
    vi.stubGlobal("isSecureContext", true); vi.stubGlobal("PublicKeyCredential", class {});
    Object.defineProperty(navigator, "credentials", {configurable: true, value: {get: vi.fn(), create: vi.fn()}});
    expect(passkeySupported()).toBe(true);
  });
  it("decodes options and passes the ceremony AbortSignal", async () => {
    const get = vi.fn().mockResolvedValue(null), create = vi.fn().mockResolvedValue(null);
    Object.defineProperty(navigator, "credentials", {configurable: true, value: {get, create}});
    const signal = new AbortController().signal;
    await browserCredential({challenge_id: "id", publicKey: {challenge: "AQI", allowCredentials: [{id: "AwQ"}]}}, "login", signal);
    expect(new Uint8Array(get.mock.calls[0][0].publicKey.challenge)).toEqual(new Uint8Array([1,2]));
    expect(new Uint8Array(get.mock.calls[0][0].publicKey.allowCredentials[0].id)).toEqual(new Uint8Array([3,4]));
    expect(get.mock.calls[0][0].signal).toBe(signal);
    await browserCredential({challenge_id: "id", publicKey: {challenge: "AQI", user: {id: "AwQ"}, excludeCredentials: [{id: "AwQ"}]}}, "register", signal);
    expect(new Uint8Array(create.mock.calls[0][0].publicKey.user.id)).toEqual(new Uint8Array([3,4]));
    expect(create.mock.calls[0][0].signal).toBe(signal);
  });
  it("serializes assertion and registration without toJSON", () => {
    const base = {id: "AQI", rawId: decodeBase64url("AQI"), type: "public-key"};
    expect(credentialJson({...base, response: {clientDataJSON: decodeBase64url("AQI"), authenticatorData: decodeBase64url("AwQ"), signature: decodeBase64url("BQY"), userHandle: decodeBase64url("Bwg")}} as unknown as Credential))
      .toMatchObject({rawId: "AQI", response: {clientDataJSON: "AQI", authenticatorData: "AwQ", signature: "BQY", userHandle: "Bwg"}});
    expect(credentialJson({...base, response: {clientDataJSON: decodeBase64url("AQI"), attestationObject: decodeBase64url("AwQ"), getTransports: () => ["internal"]}} as unknown as Credential))
      .toMatchObject({response: {attestationObject: "AwQ", transports: ["internal"]}});
    expect(() => credentialJson(null)).toThrow();
  });
});
