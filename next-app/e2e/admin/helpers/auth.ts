import { expect, type BrowserContext, type Page } from "@playwright/test";

/** Bootstrap-created test users (bootstrap-local-production.sh in stamboken-drift). */
export const ADMIN = { username: "test-admin", password: "test-admin-pass" };
export const MANAGER = {
  username: "test-gk-manager",
  password: "test-gk-pass",
};
export const OWNER = {
  username: "test-gk-owner",
  password: "test-gk-owner-pass",
};
// Mutation victims — bootstrap-created but NOT used by the legacy
// (playwright.legacy.config.ts) or demo (playwright.demo.config.ts) suites,
// so this suite may mutate them:
export const VICTIM_PROFILE = {
  username: "test-mk-manager",
  password: "test-mk-pass",
};
export const VICTIM_PASSWORD = {
  username: "test-dual",
  password: "test-dual-pass",
};
export const VICTIM_DEACTIVATE = {
  username: "test-empty",
  password: "test-empty-pass",
};
export const VICTIM_ROLE = {
  username: "test-mk-owner",
  password: "test-mk-owner-pass",
};

export type Cred = { username: string; password: string };
export type Mode = "prod" | "demo";

/**
 * Log in via POST /api/login THROUGH nginx (baseURL https://localhost) —
 * the CLAUDE.md-mandated pattern — then set the sb_mode cookie directly.
 * sb_mode is a client-writable UX cookie, not a security boundary
 * (Phase 999.2, threat T-999.2-15); the admin layout's mode gate reads it.
 * Every test file logs in fresh (no storageState) so session-killing specs
 * (21-massutloggning, 07-inaktivera-konto) cannot poison later files.
 */
export async function loginAs(
  page: Page,
  context: BrowserContext,
  cred: Cred,
  mode: Mode = "prod",
): Promise<void> {
  await context.clearCookies();
  const res = await page.request.post("/api/login", {
    data: { username: cred.username, password: cred.password },
  });
  expect(
    res.ok(),
    `login as ${cred.username} failed: ${res.status()}`,
  ).toBeTruthy();
  await context.addCookies([
    {
      name: "sb_mode",
      value: mode,
      domain: "localhost",
      path: "/",
      secure: true,
      sameSite: "Lax",
    },
  ]);
}
