import { fetchApi, ApiError } from "./api";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { MODE_COOKIE, parseMode } from "./mode";
import type { UserContext } from "./user-context";

/**
 * Fetch /user with a single retry on transient connection errors (SocketError,
 * fetch failed) to handle brief API unavailability during startup/deployments.
 * Returns null on 401 or when the API stays unreachable.
 *
 * `forceProd` bypasses mode-aware routing — used to distinguish "dead session"
 * from "valid prod session whose user row is missing in herdbook_demo" (CR-02).
 */
async function fetchUserWithRetry(
  forceProd = false,
): Promise<UserContext | null> {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      return await fetchApi<UserContext>("/user", { forceProd });
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) return null;
      if (attempt === 0) {
        console.warn("getUser: API unreachable, retrying in 1s...");
        await new Promise((r) => setTimeout(r, 1000));
        continue;
      }
      console.error(
        "getUser: API unreachable after retry, treating as unauthenticated:",
        e,
      );
      return null;
    }
  }
  return null;
}

export async function getUser(): Promise<UserContext | null> {
  const cookieStore = await cookies();
  if (!cookieStore.get("session")) return null;
  return fetchUserWithRetry();
}

/** Sign-in URL preserving the current destination for post-login return. */
async function signInUrl(): Promise<string> {
  const headersList = await headers();
  const currentUrl =
    headersList.get("x-next-url") || headersList.get("referer") || "/";
  const parsed = new URL(currentUrl, "http://localhost");
  const returnTo = encodeURIComponent(parsed.pathname + parsed.search);
  return `/auth/sign-in?return_to=${returnTo}`;
}

export async function requireUser(): Promise<UserContext> {
  const user = await getUser();
  if (!user) {
    redirect(await signInUrl());
  }
  return user;
}

export type DashboardSession =
  | { kind: "ok"; user: UserContext }
  | { kind: "missing-in-demo" };

/**
 * Dashboard session resolution with the CR-02 demo-lockout guard.
 *
 * In demo mode, /user resolves against api-test (herdbook_demo). A user
 * registered in prod AFTER the last nightly sync has no demo row yet, so the
 * demo /user call 401s even though the session is perfectly valid — without
 * this guard that cascades into a sign-in redirect loop (login sets demo mode
 * again). Distinguish the two 401 causes by re-checking /user against the PROD
 * backend (forceProd): valid there => render a friendly "not in the test
 * environment yet" page instead of redirecting; 401 there too => dead session,
 * normal sign-in redirect.
 */
export async function requireDashboardSession(): Promise<DashboardSession> {
  const cookieStore = await cookies();
  if (!cookieStore.get("session")) {
    redirect(await signInUrl());
  }

  const user = await fetchUserWithRetry();
  if (user) return { kind: "ok", user };

  const mode = parseMode(cookieStore.get(MODE_COOKIE)?.value);
  if (mode === "demo") {
    const prodUser = await fetchUserWithRetry(true);
    if (prodUser) return { kind: "missing-in-demo" };
  }

  redirect(await signInUrl());
}
