import { useCallback, useEffect, useRef, useState } from "react";
import type { SessionData } from "./types";
import { UI, t } from "./ui";

type Phase = "loading" | "login" | "app" | "error";

export function useSession() {
  const controllers = useRef(new Set<AbortController>());
  const [phase, setPhase] = useState<Phase>("loading");
  const [message, setMessage] = useState("");
  const lastHuman = useRef(Date.now());
  const lastActivitySent = useRef(0);
  const lastStorageWrite = useRef(0);
  const activityBusy = useRef(false);

  const request = useCallback(<T,>(path: string, options: RequestInit = {}) =>
    UI.api<T>(path, controllers.current, options), []);

  const showLogin = useCallback((reason = "") => {
    for (const controller of controllers.current) controller.abort();
    controllers.current.clear();
    setMessage(reason);
    setPhase("login");
  }, []);

  const acceptSession = useCallback((session: SessionData) => {
    lastHuman.current = session.last_activity * 1000;
    setMessage("");
    setPhase("app");
  }, []);

  const login = useCallback(async (password: string) => {
    const session = await request<SessionData>("/api/login", {
      method: "POST",
      body: JSON.stringify({ password })
    });
    UI.writeStorage(UI.ACTIVITY_KEY, session.last_activity * 1000);
    acceptSession(session);
  }, [acceptSession, request]);

  const logout = useCallback(async (reason = "", broadcast = true) => {
    showLogin(reason);
    if (broadcast) UI.writeStorage(UI.LOGOUT_KEY, Date.now());
    try {
      await request("/api/logout", { method: "POST", body: "{}" });
    } catch {
      // Local logout remains authoritative when the network is unavailable.
    }
  }, [request, showLogin]);

  useEffect(() => {
    request<SessionData>("/api/session")
      .then(acceptSession)
      .catch((error: Error & { status?: number }) => {
        if (error.status === 401) showLogin("");
        else {
          setMessage(error.message);
          setPhase("error");
        }
      });
    return () => {
      for (const controller of controllers.current) controller.abort();
      controllers.current.clear();
    };
  }, [acceptSession, request, showLogin]);

  useEffect(() => {
    if (phase !== "app") return;
    let activityTimer: number | null = null;

    const sendActivity = async () => {
      activityTimer = null;
      const idleSeconds = Math.max(0, (Date.now() - lastHuman.current) / 1000);
      if (activityBusy.current || idleSeconds > 60) return;
      activityBusy.current = true;
      lastActivitySent.current = Date.now();
      try {
        await request("/api/activity", {
          method: "POST",
          body: JSON.stringify({ idle_seconds: idleSeconds })
        });
      } catch (error) {
        const apiError = error as Error & { status?: number };
        if (apiError.status === 401) showLogin(apiError.message);
      } finally {
        activityBusy.current = false;
      }
    };

    const humanActivity = (event: Event) => {
      if (!event.isTrusted) return;
      lastHuman.current = Date.now();
      if (lastHuman.current - lastStorageWrite.current > 1000) {
        UI.writeStorage(UI.ACTIVITY_KEY, lastHuman.current);
        lastStorageWrite.current = lastHuman.current;
      }
      if (activityTimer === null) {
        const delay = Math.max(0, 30000 - (Date.now() - lastActivitySent.current));
        activityTimer = window.setTimeout(sendActivity, delay);
      }
    };
    const checkIdle = () => {
      if (Date.now() - lastHuman.current >= UI.IDLE_MS) logout(t("auth.idle"));
    };
    const storage = (event: StorageEvent) => {
      if (event.key === UI.LOGOUT_KEY) showLogin(t("auth.otherTab"));
      if (event.key === UI.ACTIVITY_KEY) {
        const stamp = Number(event.newValue);
        if (stamp <= Date.now() + 1000) lastHuman.current = Math.max(lastHuman.current, stamp);
      }
    };
    const events: Array<keyof DocumentEventMap> = [
      "pointerdown", "pointermove", "keydown", "wheel", "touchstart"
    ];
    for (const name of events) document.addEventListener(name, humanActivity, { passive: true });
    window.addEventListener("storage", storage);
    const idleTimer = window.setInterval(checkIdle, 1000);
    return () => {
      for (const name of events) document.removeEventListener(name, humanActivity);
      window.removeEventListener("storage", storage);
      window.clearInterval(idleTimer);
      if (activityTimer !== null) window.clearTimeout(activityTimer);
    };
  }, [logout, phase, request, showLogin]);

  return { phase, message, request, login, logout, showLogin };
}
