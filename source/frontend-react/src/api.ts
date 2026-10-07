const UI = window.HomeEnergyUI;

type RequestError = Error & { status: number; code?: string; requestId?: string | null };

// The session owns the registry. As before, its controller replaces options.signal.
export async function requestJson<T>(
  path: string,
  controllers: Set<AbortController>,
  options: RequestInit = {}
): Promise<T> {
  const controller = new AbortController();
  controllers.add(controller);
  const timeout = setTimeout(() => controller.abort(), 65000);
  try {
    const response = await fetch(path, {
      ...options,
      credentials: "same-origin",
      cache: "no-store",
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) }
    });
    let body;
    try {
      body = await response.json();
    } catch {
      const error = new Error(UI.t("error.service", { status: response.status })) as RequestError;
      error.status = response.status;
      error.requestId = response.headers.get("x-request-id");
      throw error;
    }
    if (!response.ok) {
      const code = body.error?.code;
      const key = `api.${code}`;
      const requestId = body.error?.request_id || response.headers.get("x-request-id");
      const base = UI.hasTranslation(key) ? UI.t(key) : (UI.language === "en"
        ? UI.t("error.request", { status: response.status })
        : (body.error?.message || UI.t("error.request", { status: response.status })));
      const message = requestId ? `${base}\n${UI.t("error.requestId", { id: requestId })}` : base;
      const error = new Error(message) as RequestError;
      error.status = response.status;
      error.code = code;
      error.requestId = requestId;
      throw error;
    }
    return body;
  } finally {
    clearTimeout(timeout);
    controllers.delete(controller);
  }
}
