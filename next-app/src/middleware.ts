import { NextRequest, NextResponse } from "next/server";
import { forwardedFor } from "@/lib/forwardedFor";
import {
  MODE_COOKIE,
  initialMode,
  modeCookieOptions,
  type Mode,
} from "@/lib/mode";

const API_BASE = process.env.API_INTERNAL_URL || "http://api:9090";
// Set when the lookup fails (429, timeout, API down): no new lookup from this
// browser for two minutes, so a slow or limiting API is not asked on every
// request. Short, so a promoted user is not kept in demo for long.
const RETRY_COOKIE = "sb_mode_retry";

/**
 * The mode for a session whose sb_mode cookie is missing or invalid (#227), from
 * v2_prod_access in PROD, the source of truth (as setMode does). null when the
 * user cannot be read: the cookie stays unset until a later lookup succeeds.
 */
async function modeFromProd(
  request: NextRequest,
  session: string,
): Promise<Mode | null> {
  try {
    const res = await fetch(`${API_BASE}/api/user`, {
      headers: {
        Cookie: `session=${session}`,
        ...forwardedFor(request.headers),
      },
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(500),
    });
    if (!res.ok) return null;
    const user = await res.json();
    return initialMode(!!user?.v2_prod_access);
  } catch {
    return null;
  }
}

/**
 * Routes that require a Stamboken (Flask) session: the herdbook dashboard and
 * the Payload CMS admin. Unauthenticated visits go to the single sign-in page.
 */
export async function middleware(request: NextRequest) {
  const sessionCookie = request.cookies.get("session");
  const currentPath = request.nextUrl.pathname + request.nextUrl.search;
  if (!sessionCookie) {
    const returnTo = encodeURIComponent(currentPath);
    return NextResponse.redirect(
      new URL(`/auth/sign-in?return_to=${returnTo}`, request.url),
    );
  }
  // Only a missing or invalid sb_mode costs an API call; it is a UX signal,
  // not authorization (lib/mode.ts). Set on the request too, so this render
  // already reads the resolved mode.
  const current = request.cookies.get(MODE_COOKIE)?.value;
  const lookup =
    current !== "demo" &&
    current !== "prod" &&
    !request.cookies.has(RETRY_COOKIE);
  const mode = lookup ? await modeFromProd(request, sessionCookie.value) : null;
  if (mode) request.cookies.set(MODE_COOKIE, mode);
  // Expose the path so server components (requireUser) can preserve destination.
  const response = mode
    ? NextResponse.next({ request: { headers: request.headers } })
    : NextResponse.next();
  if (mode) response.cookies.set(MODE_COOKIE, mode, modeCookieOptions);
  else if (lookup)
    response.cookies.set(RETRY_COOKIE, "1", {
      ...modeCookieOptions,
      httpOnly: true,
      maxAge: 120,
    });
  response.headers.set("x-next-url", currentPath);
  return response;
}

export const config = {
  // Node.js, not edge: forwardedFor needs node:net.
  runtime: "nodejs",
  // Protect /stamboken/*, /admin (and /admin/*), and /medlem/*. Exclude paths
  // containing a dot (static assets), Payload's own API/asset routes under
  // /admin, and the public certificate verification pages
  // (/stamboken/verifiera/* — QR landing).
  matcher: [
    "/stamboken/((?!verifiera(?:/|$))(?!.*\\.).*)",
    "/admin/:path*",
    "/medlem/((?!.*\\.).*)",
  ],
};
