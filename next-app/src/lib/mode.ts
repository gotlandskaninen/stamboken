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
 * With a session, middleware replaces a missing or invalid value with
 * {@link initialMode} before any page reads it (#227).
 */
export function parseMode(value: string | undefined): Mode {
  return value === "prod" ? "prod" : "demo";
}

/**
 * Base-dev-safe initial mode from the promotion flag:
 * - promoted (v2_prod_access) -> "prod"
 * - non-promoted with a test API configured -> "demo"
 * - non-promoted in base dev (no test API) -> "prod" (nowhere to demo against)
 */
export function initialMode(v2ProdAccess: boolean): Mode {
  const testConfigured = !!process.env.API_TEST_INTERNAL_URL;
  return v2ProdAccess || !testConfigured ? "prod" : "demo";
}

/**
 * The browser must read sb_mode (RTK Query picks demo vs. prod from it), so it
 * is NON-httpOnly; the rest mirrors the session cookie (actions.ts). It is not
 * an auth token (threat T-999.2-10). It lives as long as the Flask session
 * (PERMANENT_SESSION_LIFETIME, 31 days), so a chosen demo outlasts a browser
 * restart and middleware rarely has to look the mode up.
 */
export const modeCookieOptions = {
  httpOnly: false,
  secure: process.env.NODE_ENV === "production",
  sameSite: "lax" as const,
  path: "/",
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
