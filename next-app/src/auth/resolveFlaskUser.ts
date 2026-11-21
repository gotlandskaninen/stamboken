export type ResolveDeps = {
  sessionValue: string | undefined;
  fetchUser: () => Promise<{
    ok: boolean;
    google_email?: string | null;
    validated?: boolean;
    auth_method?: string | null;
  }>;
  findUserByEmail: (
    email: string,
  ) => Promise<{ id: number | string; email: string; role: string } | null>;
};

/**
 * Pure, testable core: session cookie -> Flask identity -> allowlist row.
 * Keys on google_email, which only a Google login writes once Google has
 * verified the address, never on the self-editable User.email. Only a
 * session that signed in with Google: an account with a role has no other.
 */
export async function resolveFlaskUser(deps: ResolveDeps) {
  if (!deps.sessionValue) return null;
  const flask = await deps.fetchUser();
  if (
    !flask.ok ||
    flask.validated !== true ||
    flask.auth_method !== "google" ||
    !flask.google_email
  )
    return null;
  const email = flask.google_email.toLowerCase();
  const row = await deps.findUserByEmail(email);
  if (!row) return null;
  return { ...row, collection: "users" as const };
}

export function readSessionCookie(headers: Headers): string | undefined {
  const cookie = headers.get("cookie") || "";
  const match = cookie.match(/(?:^|;\s*)session=([^;]+)/);
  return match ? match[1] : undefined;
}
