import type { AuthStrategy, AuthStrategyResult } from "payload";
// Relative: this file is loaded through payload.config.ts, which the Payload
// CLI runs without the "@/" alias.
import { forwardedFor } from "../lib/forwardedFor";
import { resolveFlaskUser, readSessionCookie } from "./resolveFlaskUser";

const API_BASE = process.env.API_INTERNAL_URL || "http://api:9090";

/**
 * The Flask session cookie is a browser credential, so it must not authenticate
 * a request that another site triggered (a cross-site form POST reaches
 * /cms-api as the logged-in admin). authenticate() is not told the HTTP method,
 * so rely on what browsers always send: Origin on every non-GET request, and
 * Sec-Fetch-Site on all of them. Our own origin is the Host header nginx
 * forwards (compared with the Origin's host and port); an Origin without a
 * Host fails closed.
 */
function isCrossSite(headers: Headers): boolean {
  const origin = headers.get("origin");
  if (origin !== null) {
    try {
      return new URL(origin).host !== headers.get("host");
    } catch {
      return true; // "null" (sandboxed frame, no-referrer form post)
    }
  }
  // No Origin means GET/HEAD. A link from another site may navigate here;
  // other cross-site loads (img, fetch no-cors) may not.
  return (
    headers.get("sec-fetch-site") === "cross-site" &&
    headers.get("sec-fetch-mode") !== "navigate"
  );
}

export const flaskSessionStrategy: AuthStrategy = {
  name: "flask-session",
  authenticate: async ({ headers, payload }) => {
    if (isCrossSite(headers))
      return { user: null } satisfies AuthStrategyResult;
    const sessionValue = readSessionCookie(headers);
    const user = await resolveFlaskUser({
      sessionValue,
      fetchUser: async () => {
        if (!sessionValue) return { ok: false };
        try {
          const res = await fetch(`${API_BASE}/api/user`, {
            headers: {
              Cookie: `session=${sessionValue}`,
              ...forwardedFor(headers),
            },
            cache: "no-store",
          });
          if (!res.ok) return { ok: false };
          const body = (await res.json()) as {
            google_email?: string | null;
            validated?: boolean;
          };
          return {
            ok: true,
            google_email: body?.google_email,
            validated: body?.validated,
          };
        } catch {
          return { ok: false };
        }
      },
      findUserByEmail: async (email) => {
        const { docs } = await payload.find({
          collection: "users",
          where: { email: { equals: email } },
          limit: 1,
          overrideAccess: true,
        });
        return (
          (docs[0] as { id: number | string; email: string; role: string }) ??
          null
        );
      },
    });
    if (!user) return { user: null } satisfies AuthStrategyResult;
    // Cast: the DB row satisfies the runtime shape Payload needs; missing
    // timestamp fields are only required by the generated static type.
    return { user: user as AuthStrategyResult["user"] };
  },
};
