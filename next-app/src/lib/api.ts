import { cookies, headers } from "next/headers";
import { forwardedFor } from "@/lib/forwardedFor";
import { MODE_COOKIE, parseMode } from "@/lib/mode";

const API_BASE = process.env.API_INTERNAL_URL || "http://api:9090";
// No hardcoded fallback host: leaving this undefined is what keeps base dev
// (no api-test service) on prod. Only when a test URL is explicitly configured
// does demo mode route server-side to the api-test upstream.
const API_TEST_BASE = process.env.API_TEST_INTERNAL_URL;

type FetchApiOptions = RequestInit & {
  timeout?: number;
  /**
   * Bypass mode-aware routing and always hit the PROD backend. For checks
   * where prod is the source of truth regardless of the caller's sb_mode
   * cookie (e.g. setMode's v2_prod_access re-check — code review WR-01).
   */
  forceProd?: boolean;
};

// WR-04 guard: warn once per server process when a demo-mode request must fall
// back to prod because API_TEST_INTERNAL_URL is unset. Production-only — base
// dev legitimately has no api-test service and would spam otherwise.
let warnedDemoFallback = false;

export async function fetchApi<T>(
  path: string,
  options?: FetchApiOptions,
): Promise<T> {
  const cookieStore = await cookies();
  const { timeout = 10000, forceProd = false, ...fetchOptions } = options ?? {};

  // Mode-aware base URL: reuse the already-fetched cookieStore (no second
  // cookies() call). Demo routes to api-test ONLY when a test URL is configured;
  // base dev (API_TEST_BASE unset) always falls back to prod.
  const mode = parseMode(cookieStore.get(MODE_COOKIE)?.value);
  // parseMode(undefined) is "demo", so a visitor with no sb_mode cookie reads as
  // demo. Only a signed-in user (login sets sb_mode together with the session)
  // can be in demo; an anonymous request must reach prod or it lands in the
  // nightly-wiped demo database.
  const signedIn = !!cookieStore.get("session")?.value;
  if (
    mode === "demo" &&
    !API_TEST_BASE &&
    !warnedDemoFallback &&
    process.env.NODE_ENV === "production"
  ) {
    warnedDemoFallback = true;
    console.warn(
      "fetchApi: sb_mode=demo but API_TEST_INTERNAL_URL is unset — " +
        "demo-mode requests are silently served from PROD. Configure " +
        "API_TEST_INTERNAL_URL (and the matching NEXT_PUBLIC_API_TEST_URL " +
        "build arg), or investigate why a demo cookie exists in this deployment.",
    );
  }
  const base =
    !forceProd && mode === "demo" && signedIn && API_TEST_BASE
      ? API_TEST_BASE
      : API_BASE;

  // Forward ALL cookies (not just session) — more robust if Flask
  // or middleware adds additional cookies in the future
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");
  const clientIp = forwardedFor(await headers());
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  // Skip Content-Type: application/json for FormData bodies
  // (FormData sets its own Content-Type with boundary automatically)
  const isFormData =
    typeof FormData !== "undefined" && fetchOptions?.body instanceof FormData;
  const defaultHeaders: Record<string, string> = {
    ...(cookieHeader ? { Cookie: cookieHeader } : {}),
    ...clientIp,
  };
  if (!isFormData) {
    defaultHeaders["Content-Type"] = "application/json";
  }

  try {
    const res = await fetch(`${base}/api${path}`, {
      ...fetchOptions,
      cache: "no-store", // Never cache authenticated responses
      redirect: "manual", // Catch legacy @login_required 302 redirects
      signal: controller.signal,
      headers: {
        ...defaultHeaders,
        ...fetchOptions?.headers,
      },
    });

    clearTimeout(timeoutId);

    // Legacy @login_required returns 302 redirect to login page,
    // not JSON 401. Detect and convert to ApiError.
    if (res.status === 302) {
      throw new ApiError({
        status: 401,
        title: "Not authenticated",
        detail: "Session expired",
      });
    }

    if (!res.ok) {
      let problem;
      try {
        const body = await res.json();
        // Normalize: RFC 9457 has {type, title, status, detail, instance} plus arbitrary
        // extension members. Legacy Flask has {status: "error", message: "..."}.
        // Always use the HTTP status code as the canonical status; the
        // extensions are kept so callers can branch on machine-readable data
        // (Phase 19 kontokoppling reads `type` + `conveys_herds`) instead of
        // parsing the Swedish `detail`.
        const rest: Record<string, unknown> = {
          ...(body as Record<string, unknown>),
        };
        for (const key of [
          "type",
          "title",
          "status",
          "detail",
          "instance",
          "message",
        ])
          delete rest[key];
        problem = {
          status: res.status,
          title: body.title || res.statusText,
          detail: body.detail || body.message || res.statusText,
          type: typeof body.type === "string" ? body.type : "about:blank",
          extensions: rest,
        };
      } catch {
        const text = await res.text().catch(() => "");
        problem = {
          status: res.status,
          title: res.statusText,
          detail: text.slice(0, 200) || `HTTP ${res.status} ${res.statusText}`,
          type: "about:blank",
          extensions: {},
        };
      }
      throw new ApiError(problem);
    }

    if (res.status === 204) return undefined as T;
    return res.json();
  } catch (e) {
    clearTimeout(timeoutId);
    if (e instanceof ApiError) throw e;
    if (e instanceof DOMException && e.name === "AbortError") {
      throw new ApiError({
        status: 408,
        title: "Timeout",
        detail: "Servern svarade inte i tid",
      });
    }
    throw e;
  }
}

export class ApiError extends Error {
  status: number;
  title: string;
  detail: string;
  /** RFC 9457 problem type URI; "about:blank" when the body carries none. */
  type: string;
  /** The problem body minus type/title/status/detail/message. */
  extensions: Record<string, unknown>;

  constructor(problem: {
    status: number;
    title: string;
    detail: string;
    type?: string;
    extensions?: Record<string, unknown>;
  }) {
    super(problem.detail);
    this.status = problem.status;
    this.title = problem.title;
    this.detail = problem.detail;
    this.type = problem.type ?? "about:blank";
    this.extensions = problem.extensions ?? {};
  }
}
