import { useEffect, useRef, useState } from "react";
import { t } from "../ui";
import { passkeySupported, type PasskeyOptions, type JsonRequest } from "../passkey";

type Complete = (options: PasskeyOptions, kind: "login" | "register", label?: string) => Promise<void>;
export function PasskeyLogin({ prepare, complete, disabled }: {
  prepare: () => Promise<PasskeyOptions>; complete: Complete; disabled: boolean;
}) {
  const [options, setOptions] = useState<PasskeyOptions | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  if (!passkeySupported()) return <p className="muted">{t("passkey.unsupported")}</p>;
  const click = async () => {
    setBusy(true); setMessage("");
    try {
      if (options) { await complete(options, "login"); if (mounted.current) setOptions(null); }
      else { const prepared = await prepare(); if (mounted.current) setOptions(prepared); }
    } catch (reason) {
      if (mounted.current) { setOptions(null); setMessage(passkeyError(reason)); }
    } finally { if (mounted.current) setBusy(false); }
  };
  return <div>
    <button type="button" disabled={disabled || busy} onClick={click}>{t(options ? "passkey.continue" : "passkey.login")}</button>
    <p className="muted">{t("passkey.fallback")}</p>
    <p role="status">{message}</p>
  </div>;
}

function passkeyError(reason: unknown) {
  const error = reason as Error;
  return error.name === "NotAllowedError" || error.name === "AbortError" ? t("passkey.cancelled") : error.message;
}

export function PasskeyManager({ request, complete, showLogin }: {
  request: JsonRequest; complete: Complete; showLogin: (reason?: string) => void;
}) {
  const [permission, setPermission] = useState("");
  const [label, setLabel] = useState("");
  const [options, setOptions] = useState<PasskeyOptions | null>(null);
  const [rows, setRows] = useState<Array<{ key: string; label: string; revoked: boolean }>>([]);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const run = async (operation: "register" | "list" | "revoke", key?: string) => {
    setBusy(true); setMessage("");
    try {
      if (operation === "register") {
        if (options) {
          await complete(options, "register", label);
          if (mounted.current) { setOptions(null); setMessage(t("passkey.registered")); }
        } else {
          const result = await request<PasskeyOptions>("/api/passkey/register/options", { method: "POST", body: JSON.stringify({ permission }) });
          if (mounted.current) { setPermission(""); setOptions(result); }
        }
      } else {
        const result = await request<{ credentials: typeof rows }>("/api/passkey/manage", {
          method: "POST", body: JSON.stringify({ operation, permission, key })
        });
        if (mounted.current) {
          if (operation === "list") setRows(result.credentials);
          else { setPermission(""); setRows(rows.map(row => row.key === key ? { ...row, revoked: true } : row)); setMessage(t("passkey.revoked")); }
        }
      }
    } catch (reason) {
      if (mounted.current) {
        setOptions(null); setMessage(passkeyError(reason));
        if ((reason as Error & {status?: number}).status === 401) showLogin((reason as Error).message);
      }
    } finally { if (mounted.current) setBusy(false); }
  };
  return <details>
    <summary>{t("passkey.manage")}</summary>
    <p className="muted">{t("passkey.permissionHelp")}</p>
    <label>{t("passkey.permission")}<input type="password" autoComplete="off" value={permission}
      onChange={event => setPermission(event.target.value)} disabled={busy || !!options} /></label>
    <label>{t("passkey.label")}<input maxLength={80} value={label}
      onChange={event => setLabel(event.target.value)} disabled={busy || !!options} /></label>
    <button type="button" disabled={busy || !passkeySupported() || (!options && (!permission || !label.trim()))}
      onClick={() => run("register")}>{t(options ? "passkey.continue" : "passkey.register")}</button>
    <button type="button" disabled={busy || !!options || !permission} onClick={() => run("list")}>{t("passkey.list")}</button>
    {options && <button type="button" disabled={busy} onClick={() => { setOptions(null); setMessage(t("passkey.cancelled")); }}>{t("passkey.cancel")}</button>}
    <ul>{rows.map(row => <li key={row.key}>{row.label} · {t(row.revoked ? "passkey.revoked" : "passkey.active")}
      {!row.revoked && <button type="button" disabled={busy || !!options || !permission}
        onClick={() => run("revoke", row.key)}>{t("passkey.revoke")}</button>}</li>)}</ul>
    <p role="status">{message}</p>
  </details>;
}
