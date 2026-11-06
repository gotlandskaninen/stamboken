import type { BrowserContext, Page } from "@playwright/test";

export const TEST_USERS = {
  owner: { username: "test-gk-owner", password: "test-gk-owner-pass" },
  admin: { username: "test-admin", password: "test-admin-pass" },
  manager: { username: "test-gk-manager", password: "test-gk-pass" },
} as const;

export type TestRole = keyof typeof TEST_USERS;

/**
 * Log in via Flask /api/login and save the browser storage state.
 *
 * Login goes directly to Flask (port 9090) for speed, then the session
 * cookie is copied to the Next.js origin (port 3000) so middleware
 * recognizes the session on page navigation.
 */
export async function loginAndSaveState(
  page: Page,
  context: BrowserContext,
  role: TestRole,
  statePath: string,
  apiBaseURL = "http://localhost:9090",
): Promise<void> {
  const { username, password } = TEST_USERS[role];
  const response = await page.request.post(`${apiBaseURL}/api/login`, {
    data: { username, password },
  });
  if (!response.ok()) {
    throw new Error(
      `Login as ${role} (${username}) failed: ${response.status()}`,
    );
  }

  // Extract session cookie from Flask response and set it for the Next.js
  // origin (localhost:3000). Playwright's page.request sets cookies scoped
  // to the request origin (port 9090), but tests navigate to port 3000.
  const cookies = await context.cookies();
  const sessionCookie = cookies.find((c) => c.name === "session");
  if (sessionCookie) {
    await context.addCookies([
      {
        name: sessionCookie.name,
        value: sessionCookie.value,
        domain: "localhost",
        path: "/",
        httpOnly: sessionCookie.httpOnly,
        secure: false,
        sameSite: "Lax",
      },
    ]);
  }

  await context.storageState({ path: statePath });
}

/**
 * Log in inline during a test (no storageState file).
 * Use for ad-hoc role switches within a test (e.g., test-empty user).
 */
export async function loginInline(
  page: Page,
  context: BrowserContext,
  credentials: { username: string; password: string },
  apiBaseURL = "http://localhost:9090",
): Promise<void> {
  await context.clearCookies();
  const response = await page.request.post(`${apiBaseURL}/api/login`, {
    data: credentials,
  });
  if (!response.ok()) {
    throw new Error(
      `Inline login as ${credentials.username} failed: ${response.status()}`,
    );
  }
  // Copy session cookie to localhost (all ports)
  const cookies = await context.cookies();
  const sessionCookie = cookies.find((c) => c.name === "session");
  if (sessionCookie) {
    await context.addCookies([
      {
        name: sessionCookie.name,
        value: sessionCookie.value,
        domain: "localhost",
        path: "/",
        httpOnly: sessionCookie.httpOnly,
        secure: false,
        sameSite: "Lax",
      },
    ]);
  }
}
