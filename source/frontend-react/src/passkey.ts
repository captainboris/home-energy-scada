/** Browser serialization only; all authorization and verification is server-side. */
export interface PasskeyOptions {
  challenge_id: string;
  publicKey: Record<string, unknown>;
}
export type JsonRequest = <T>(path: string, options?: RequestInit) => Promise<T>;

export function passkeySupported() {
  return window.isSecureContext && typeof PublicKeyCredential !== "undefined"
    && typeof navigator.credentials?.get === "function" && typeof navigator.credentials?.create === "function";
}

export function decodeBase64url(value: string): ArrayBuffer {
  const text = atob(value.replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(text, character => character.charCodeAt(0)).buffer;
}

function encode(value: ArrayBuffer | null) {
  if (!value) return null;
  return btoa(String.fromCharCode(...new Uint8Array(value))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function browserCredential(options: PasskeyOptions, kind: "login" | "register", signal: AbortSignal) {
  const publicKey = { ...options.publicKey, challenge: decodeBase64url(options.publicKey.challenge as string) };
  if (kind === "login") {
    const allowed = publicKey as unknown as PublicKeyCredentialRequestOptions;
    if (allowed.allowCredentials) allowed.allowCredentials = allowed.allowCredentials.map(item => ({ ...item, id: decodeBase64url(item.id as unknown as string) }));
    // Called directly from a user gesture; options are prepared on a separate click.
    return navigator.credentials.get({ publicKey: allowed, signal });
  }
  const creation = publicKey as unknown as PublicKeyCredentialCreationOptions;
  creation.user = { ...creation.user, id: decodeBase64url(creation.user.id as unknown as string) };
  if (creation.excludeCredentials) creation.excludeCredentials = creation.excludeCredentials.map(item => ({ ...item, id: decodeBase64url(item.id as unknown as string) }));
  return navigator.credentials.create({ publicKey: creation, signal });
}

export function credentialJson(value: Credential | null) {
  if (!value) throw new DOMException("Cancelled", "NotAllowedError");
  const credential = value as PublicKeyCredential;
  const response = credential.response;
  const base = { id: credential.id, rawId: encode(credential.rawId), type: credential.type };
  if ("attestationObject" in response) {
    const registration = response as AuthenticatorAttestationResponse;
    return { ...base, response: { clientDataJSON: encode(response.clientDataJSON),
      attestationObject: encode(registration.attestationObject), transports: registration.getTransports?.() || [] } };
  }
  const assertion = response as AuthenticatorAssertionResponse;
  return { ...base, response: { clientDataJSON: encode(response.clientDataJSON),
    authenticatorData: encode(assertion.authenticatorData), signature: encode(assertion.signature), userHandle: encode(assertion.userHandle) } };
}
