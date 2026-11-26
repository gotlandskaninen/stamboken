/**
 * Shared "mode" contract for the v2 stamboken demo/prod toggle.
 *
 * This is the single canonical source for the mode type, cookie name,
 * allow-list validation, and the client-side cookie reader. Every fetch path
 * (server `lib/api.ts` and client `redux/api/apiSlice.ts`) imports from here.
 *
 * SECURITY (threat T-999.2-05, ASVS V3/V5): `sb_mode` is a NON-httpOnly UX
 * signal ONLY. It selects which dataset the v2 UI shows (demo vs. prod). It is
 * NOT an authentication or authorization token and must NEVER be read as, or
 * substituted for, the httpOnly `session` cookie. Actual prod-vs-demo
 * authorization is enforced elsewhere (nginx path routing + Flask auth); a user
 * tampering with `sb_mode` in devtools gains nothing they do not already have.
 * `parseMode()` strictly allow-lists to `demo|prod` with a fail-safe `demo`
 * default so an arbitrary cookie value cannot produce undefined routing.
 */

export type Mode = "demo" | "prod";

/** Name of the non-httpOnly UX cookie carrying the current mode. */
export const MODE_COOKIE = "sb_mode";

/**
 * Validate a raw cookie value against the `demo|prod` allow-list.
 * Returns `"prod"` only for the exact string `"prod"`; everything else
 * (undefined, unknown values, wrong case) fail-safes to `"demo"` (ASVS V5).
 * With a session, on routes the middleware matches, a missing or invalid
 * value is replaced with {@link initialMode} before any page reads it (#227).
 */
export function parseMode(value: string | undefined): Mode {
  return value === "prod" ? "prod" : "demo";
}

/**
 * Host of the test environment (demo). The same app serves it and production;
 * on this host the mode is always "demo". Override with TEST_HOST.
 */
export const TEST_HOST = (
  process.env.TEST_HOST || "sb.gotlandskaninen.se"
).toLowerCase();

/** Production origin that a switch to "prod" on the test host goes to. */
export const PROD_ORIGIN =
  process.env.PROD_ORIGIN || "https://gotlandskaninen.se";

/** True when the request was made to {@link TEST_HOST} (port ignored). */
export function isTestHost(h: Pick<Headers, "get">): boolean {
  const raw = h.get("x-forwarded-host") || h.get("host") || "";
  const host = raw.split(",")[0].trim().toLowerCase().replace(/:\d+$/, "");
  return host === TEST_HOST;
}

/**
 * Base-dev-safe initial mode from the promotion flag:
 * - on the test host -> always "demo"
 * - promoted (v2_prod_access) -> "prod"
 * - non-promoted with a test API configured -> "demo"
 * - non-promoted in base dev (no test API) -> "prod" (nowhere to demo against)
 */
export function initialMode(
  v2ProdAccess: boolean,
  h?: Pick<Headers, "get">,
): Mode {
  if (h && isTestHost(h)) return "demo";
  const testConfigured = !!process.env.API_TEST_INTERNAL_URL;
  return v2ProdAccess || !testConfigured ? "prod" : "demo";
}

/**
 * Cookie settings that must match Flask's session config (herdbook.py,
 * APP.config): SameSite "Lax", Secure in production only.
 */
export const sessionCookieOptions = {
  httpOnly: true,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
};

/**
 * The browser must read sb_mode (RTK Query picks demo vs. prod from it), so it
 * is NON-httpOnly; the rest mirrors the session cookie. It is not
 * an auth token (threat T-999.2-10). It lives as long as the Flask session
 * (PERMANENT_SESSION_LIFETIME, 31 days), so a chosen demo outlasts a browser
 * restart and middleware rarely has to look the mode up.
 */
export const modeCookieOptions = {
  ...sessionCookieOptions,
  httpOnly: false,
  maxAge: 31 * 24 * 60 * 60,
};

/**
 * SSR-safe client reader: extracts `sb_mode` from `document.cookie` and returns
 * its validated {@link Mode}. Returns `"demo"` when `document` is unavailable
 * (server render) or the cookie is absent.
 */
export function readModeCookieClient(): Mode {
  if (typeof document === "undefined") return "demo";
  const match = document.cookie
    .split("; ")
    .find((row) => row.startsWith(`${MODE_COOKIE}=`));
  return parseMode(match?.slice(MODE_COOKIE.length + 1));
}
