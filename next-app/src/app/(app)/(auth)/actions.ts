"use server";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { refresh, revalidatePath } from "next/cache";
import { fetchApi } from "@/lib/api";
import { forwardedFor } from "@/lib/forwardedFor";
import {
  MODE_COOKIE,
  PROD_ORIGIN,
  isTestHost,
  initialMode,
  modeCookieOptions,
  parseMode,
  sessionCookieOptions,
  type Mode,
} from "@/lib/mode";

const API_BASE = process.env.API_INTERNAL_URL || "http://api:9090";

// Flask-Limiter answers 429 after too many attempts from one address.
const TOO_MANY_ATTEMPTS =
  "För många inloggningsförsök. Vänta en minut och försök igen.";

/**
 * Parse the session value from a Set-Cookie header string.
 * Flask's Set-Cookie looks like: session=<value>; HttpOnly; Path=/; ...
 */
function extractSessionValue(setCookieHeader: string): string | null {
  const match = setCookieHeader.match(/session=([^;]+)/);
  return match ? match[1] : null;
}

// The session cookie's settings, shared with sb_mode (lib/mode.ts).
const cookieOptions = { ...sessionCookieOptions };

/**
 * Validate return_to is a same-site path (prevent open redirect). The client
 * resolves it with new URL(location, currentUrl): a second "/" or a "\" after
 * the first slash makes it protocol-relative, and the parser drops tab/CR/LF
 * first, so "/<TAB>/host" is "//host" too.
 */
function safeReturnTo(returnTo?: string): string {
  if (
    typeof returnTo !== "string" ||
    !/^\/(?![/\\])/.test(returnTo) ||
    /[\t\r\n]/.test(returnTo)
  ) {
    return "/stamboken/min-besattning";
  }
  return returnTo;
}

export async function loginWithGoogle(credential: string, returnTo?: string) {
  const res = await fetch(`${API_BASE}/api/auth/google`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...forwardedFor(await headers()),
    },
    body: JSON.stringify({ credential }),
  });

  if (res.status === 429) return { error: TOO_MANY_ATTEMPTS };
  if (!res.ok) {
    // The domain restriction is the only 403 this endpoint returns — surface
    // it in Swedish (Flask's message is English) with an actionable next step.
    if (res.status === 403) {
      return {
        error:
          "Endast @gotlandskaninen.se-konton kan användas för Google-inloggning. " +
          "Välj ditt föreningskonto i Googles kontoväljare, eller logga in med användarnamn och lösenord.",
      };
    }
    // /api/auth/google returns {"error": "..."} on failure (not {"detail": "..."})
    const body = await res.json().catch(() => ({ error: "Login failed" }));
    // A workspace account with no Stamboken account linked to it yet.
    if (body.error === "User not found or not authorized") {
      return {
        error:
          "Ditt föreningskonto är inte kopplat till Stamboken än. Kontakta administratören.",
      };
    }
    return { error: body.error || "Login failed" };
  }

  // Read the user body to resolve v2_prod_access (Plan 01's frontend_data key).
  // The success path previously only read the Set-Cookie header, so this is a
  // new read; the session cookie below still comes from the header, not the body.
  const body = await res.json().catch(() => ({}));

  // Capture Flask's session cookie and set it on the browser
  const setCookie = res.headers.get("set-cookie");
  const sessionValue = setCookie ? extractSessionValue(setCookie) : null;
  if (!sessionValue) {
    console.error(
      "loginWithGoogle: succeeded but no session cookie from Flask",
    );
    return { error: "Login failed — session could not be created" };
  }
  const cookieStore = await cookies();
  cookieStore.set("session", sessionValue, cookieOptions);
  cookieStore.set(
    MODE_COOKIE,
    initialMode(!!body.v2_prod_access, await headers()),
    modeCookieOptions,
  );

  redirect(safeReturnTo(returnTo));
}

export async function loginWithPassword(
  username: string,
  password: string,
  returnTo?: string,
) {
  const res = await fetch(`${API_BASE}/api/login`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...forwardedFor(await headers()),
    },
    body: JSON.stringify({ username, password }),
  });

  if (res.status === 429) return { error: TOO_MANY_ATTEMPTS };
  // /api/login returns 401 (via get_user()) on failed login, 200 + user on success.
  // 5xx = real server error, 401 = wrong credentials.
  if (res.status >= 500) {
    console.error("loginWithPassword: HTTP", res.status);
    return { error: "Inloggning misslyckades. Försök igen senare." };
  }
  const body = await res.json().catch(() => null);
  // Success is the HTTP status plus the user id: hbuser.username is nullable
  // (and "" from a blank admin form), so it cannot tell success from failure.
  if (!res.ok || !body?.id) {
    return { error: "Felaktigt användarnamn eller lösenord" };
  }

  const setCookie = res.headers.get("set-cookie");
  const sessionValue = setCookie ? extractSessionValue(setCookie) : null;
  if (!sessionValue) {
    console.error(
      "loginWithPassword: succeeded but no session cookie from Flask",
    );
    return { error: "Login failed — session could not be created" };
  }
  const cookieStoreForPw = await cookies();
  cookieStoreForPw.set("session", sessionValue, cookieOptions);
  cookieStoreForPw.set(
    MODE_COOKIE,
    initialMode(!!body.v2_prod_access, await headers()),
    modeCookieOptions,
  );

  redirect(safeReturnTo(returnTo));
}

/**
 * Flip the sb_mode cookie without re-login (used by the promoted-only dropdown
 * toggle). Defense in depth (threat T-999.2-09): re-check v2_prod_access
 * server-side and refuse to set "prod" for a non-promoted user, even though the
 * toggle only renders for promoted users. Not an auth boundary — see lib/mode.ts.
 */
export async function setMode(target: Mode) {
  const normalized = parseMode(target);

  // The test host is demo only; production lives on its own origin.
  if (normalized === "prod" && isTestHost(await headers()))
    redirect(`${PROD_ORIGIN}/stamboken/byt-till-prod`);

  // The re-check MUST read the PROD backend (forceProd): hbuser in prod is the
  // source of truth for promotion. The default mode-aware path would consult
  // the nightly demo copy while the current cookie is demo — blocking
  // freshly-promoted users until the sync, and missing same-day demotion
  // (code review WR-01).
  let promoted = false;
  try {
    const user = await fetchApi<{ v2_prod_access?: boolean }>("/user", {
      forceProd: true,
    });
    promoted = !!user?.v2_prod_access;
  } catch {
    // 401 / API unreachable → fail-safe: treat as non-promoted.
    promoted = false;
  }
  const effective: Mode =
    normalized === "prod" && !promoted ? "demo" : normalized;

  const cookieStore = await cookies();
  cookieStore.set(MODE_COOKIE, effective, modeCookieOptions);
  // Re-resolve the server-rendered ModeProvider/banner for the stamboken layout.
  revalidatePath("/stamboken", "layout");
}

export async function logout() {
  const cookieStore = await cookies();
  const session = cookieStore.get("session");
  if (session) {
    try {
      await fetch(`${API_BASE}/api/logout`, {
        headers: {
          Cookie: `session=${session.value}`,
          ...forwardedFor(await headers()),
        },
      });
    } catch (e) {
      // Best-effort: Flask session will expire naturally.
      // Browser cookie deletion below is what matters.
      console.error("Failed to invalidate Flask session:", e);
    }
  }
  cookieStore.delete("session");
  // Also clear the sb_mode UX cookie so the next login re-derives it from
  // v2_prod_access — otherwise a promoted user's "prod" survives logout and a
  // login path that doesn't set the cookie would inherit it (code review WR-02).
  cookieStore.delete(MODE_COOKIE);
  // Don't redirect here — the client does a full page reload (window.location.href)
  // to reset Google Identity Services state. Server Action redirect() does client-side
  // navigation which keeps Google's disableAutoSelect() in effect.
}

type LoginResult =
  | {
      error:
        | "unavailable"
        | "invalidCode"
        | "invalidLink"
        | "expired"
        | "accountConflict"
        | "rulesChanged";
    }
  | { switchFrom: number }
  | { demoAccountCreated: true };

async function postCodeLogin(path: string, body: Record<string, unknown>) {
  const store = await cookies();
  const cookie = ["session", "login_request"]
    .map((name) => store.get(name))
    .filter((entry) => entry !== undefined)
    .map(({ name, value }) => `${name}=${value}`)
    .join("; ");
  try {
    const response = await fetch(`${API_BASE}/api/v2/login/${path}`, {
      method: "POST",
      cache: "no-store",
      redirect: "error",
      signal: AbortSignal.timeout(10000),
      headers: {
        "Content-Type": "application/json",
        Cookie: cookie,
        ...forwardedFor(await headers()),
      },
      body: JSON.stringify(body),
    });
    return { response, data: await response.json() };
  } catch {
    return null;
  }
}

function responseCookie(response: Response, name: string) {
  const cookie = response.headers
    .getSetCookie()
    .find((line) => line.startsWith(name + "="));
  return cookie?.split(";", 1)[0].slice(name.length + 1);
}

export async function requestLoginCode(email: string, returnTo?: string) {
  const result = await postCodeLogin("kod", { email });
  if (!result?.response.ok) return false;
  const value = responseCookie(result.response, "login_request");
  if (!value) return false;
  const store = await cookies();
  const options = { ...cookieOptions, maxAge: 600 };
  store.set("login_request", value, options);
  // The mail link opens a new tab in the browser that requested this code.
  // fetchApi forwards cookie values as they are, so only plain path characters.
  const path = returnTo && safeReturnTo(returnTo);
  if (path && /^[\w\-./?=&]+$/.test(path))
    store.set("login_return_to", path, options);
  else store.delete("login_return_to");
  return true;
}

export async function lookupLoginLink(token: string) {
  const result = await postCodeLogin("lank/uppslag", { token });
  if (!result?.response.ok || typeof result.data?.name !== "string")
    return null;
  const { name, switch_from } = result.data;
  if (switch_from !== null && !Number.isInteger(switch_from)) return null;
  return { name: name as string, switchFrom: switch_from as number | null };
}

async function finishCodeLogin(
  path: "kod/verifiera" | "lank" | "skapa-konto",
  body: Record<string, unknown>,
  returnTo?: string,
): Promise<LoginResult> {
  const result = await postCodeLogin(path, body);
  if (!result || result.response.status >= 500) return { error: "unavailable" };
  const { response, data } = result;
  if (!response.ok) {
    if (
      response.status === 409 &&
      path !== "skapa-konto" &&
      Number.isInteger(data?.switch_from)
    )
      return { switchFrom: data.switch_from };
    if (path === "skapa-konto") {
      if (response.status === 409) return { error: "accountConflict" };
      if (response.status === 412) return { error: "rulesChanged" };
      return { error: "expired" };
    }
    return { error: path === "lank" ? "invalidLink" : "invalidCode" };
  }

  const session = responseCookie(response, "session");
  if (
    !session ||
    (data?.pending !== true && typeof data?.v2_prod_access !== "boolean")
  )
    return { error: "unavailable" };
  const store = await cookies();
  if (path === "lank") returnTo = store.get("login_return_to")?.value;
  store.set("session", session, cookieOptions);
  store.delete("login_request");
  store.delete("login_return_to");
  const mode =
    data.pending === true
      ? initialMode(true, await headers())
      : initialMode(data.v2_prod_access, await headers());
  store.set(MODE_COOKIE, mode, modeCookieOptions);
  const destination = safeReturnTo(returnTo);
  if (data.pending === true) {
    redirect(
      returnTo
        ? `/auth/skapa-konto?return_to=${encodeURIComponent(destination)}`
        : "/auth/skapa-konto",
    );
  }
  if (path === "skapa-konto" && mode === "demo")
    return { demoAccountCreated: true };
  redirect(destination);
}

export async function verifyLoginCode(
  code: string,
  returnTo?: string,
  confirmUserId?: number,
) {
  return finishCodeLogin(
    "kod/verifiera",
    { code, confirm_user_id: confirmUserId },
    returnTo,
  );
}

export async function redeemLoginLink(token: string, confirmUserId?: number) {
  return finishCodeLogin("lank", { token, confirm_user_id: confirmUserId });
}

export type DisplayedRules = { version: string; sha256: string };

export async function createMemberAccount(
  accepted: boolean,
  rules: DisplayedRules,
  returnTo?: string,
): Promise<LoginResult> {
  if (accepted !== true || !rules?.version || !rules.sha256)
    return { error: "rulesChanged" };
  const result = await finishCodeLogin(
    "skapa-konto",
    { accepted, rules_version: rules.version, rules_sha256: rules.sha256 },
    returnTo,
  );
  if ("error" in result && result.error === "rulesChanged") refresh();
  return result;
}
