import { FormEvent, ReactNode, useState } from "react";
import type { Period } from "../types";
import { UI, t, useLanguage } from "../ui";

export function Header({ page, period, onLogout }: {
  page: "overview" | "daily";
  period: Period;
  onLogout: () => void;
}) {
  const { language, setLanguage } = useLanguage();
  const query = window.location.search;
  return <header>
    <div>
      <div className="eyebrow">HOME ENERGY / 06 · REACT + ECHARTS</div>
      <h1>{t(page === "overview" ? "app.title" : "daily.title")}</h1>
      <p className="muted">{t(page === "overview" ? "overview.subtitle" : "daily.subtitle")}</p>
    </div>
    <div className="actions">
      <nav className="nav" aria-label={t("nav.label")}>
        <a className={page === "overview" ? "active" : ""} href={`/${query}`}>{t("nav.overview")}</a>
        <a className={page === "daily" ? "active" : ""} href={`/daily${query}`}>{t("nav.daily")}</a>
      </nav>
      <div className="language-toggle" aria-label="Language">
        <button type="button" className={language === "zh-CN" ? "active" : ""}
          aria-pressed={language === "zh-CN"} onClick={() => setLanguage("zh-CN")}>中文</button>
        <span>|</span>
        <button type="button" className={language === "en" ? "active" : ""}
          aria-pressed={language === "en"} onClick={() => setLanguage("en")}>EN</button>
      </div>
      <span className="pill">FOX · HYBRID HISTORIAN</span>
      <button type="button" onClick={onLogout}>{t("common.logout")}</button>
    </div>
  </header>;
}

export function AuthLoading({ message }: { message?: string }) {
  return <section className="auth-loading" aria-live="polite">
    <span className="spinner" aria-hidden="true" />
    <div>{message || t("common.checkingSession")}</div>
  </section>;
}

export function Login({ message, onLogin }: {
  message: string;
  onLogin: (password: string) => Promise<void>;
}) {
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(message);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await onLogin(password);
      setPassword("");
    } catch (reason) {
      setError((reason as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return <section className="login">
    <h2>{t("login.title")}</h2>
    <p className="muted">{t("login.subtitle")}</p>
    <form onSubmit={submit}>
      <label htmlFor="password">{t("login.password")}</label>
      <input id="password" type="password" autoComplete="current-password" required minLength={10}
        maxLength={256} value={password} onChange={event => setPassword(event.target.value)} />
      <button className="primary" type="submit" disabled={busy}>{busy ? t("common.loading") : t("login.submit")}</button>
    </form>
    <p className="error" role="alert">{error}</p>
  </section>;
}

export function PageState({ phase, message, onLogin, children }: {
  phase: "loading" | "login" | "app" | "error";
  message: string;
  onLogin: (password: string) => Promise<void>;
  children: ReactNode;
}) {
  if (phase === "loading") return <AuthLoading />;
  if (phase === "error") return <AuthLoading message={message} />;
  if (phase === "login") return <Login message={message} onLogin={onLogin} />;
  return <>{children}</>;
}

export function formatRange(period: Period) {
  if (period.mode === "other") {
    return `${UI.displayDateTime(period.fromDate, period.fromTime)} — ${UI.displayDateTime(period.toDate, period.toTime)} · ${t("range.melbourne")}`;
  }
  const finish = UI.localInput(period.endMs - 1).date;
  return `${UI.displayDateTime(period.fromDate, "00:00")} — ${UI.displayDateTime(finish, "23:59")} · ${t("range.melbourne")}`;
}
