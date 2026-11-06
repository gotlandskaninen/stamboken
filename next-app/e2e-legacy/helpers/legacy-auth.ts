import fs from "node:fs";
import type { BrowserContext, Page } from "@playwright/test";
import { TEST_USERS as SHARED_USERS } from "../../e2e-shared/auth";

/**
 * Legacy base URL — goes through nginx to the legacy SPA.
 *
 * Default: the local-production host. Phase 20's audit run overrides it with
 * LEGACY_BASE_URL=https://stamboken.gotlandskaninen.se:18443, which is a REAL
 * production hostname resolved to loopback by Chromium's
 * --host-resolver-rules (playwright.legacy.config.ts). Node-side HTTP does not
 * honour that flag, so login goes through an in-page fetch() — never
 * page.request.
 */
const BASE_URL = process.env.LEGACY_BASE_URL ?? "https://stamboken.localhost";

type TestUser = { username: string; password: string };

interface AuditUsersFile {
  targets: { largest_herd: { genebank: number } };
  users: Record<string, TestUser>;
}

/**
 * Credentials. With LEGACY_USERS_FILE set (Phase 20 audit) the synthetic audit
 * users are used instead of the shared local-production ones, which do not
 * exist on the audit copy of the production database.
 */
function resolveUsers(): {
  admin: TestUser;
  gkOwner: TestUser;
  gkManager: TestUser;
} {
  const file = process.env.LEGACY_USERS_FILE;
  if (!file) {
    return {
      admin: SHARED_USERS.admin,
      gkOwner: SHARED_USERS.owner,
      gkManager: SHARED_USERS.manager,
    };
  }
  const data = JSON.parse(fs.readFileSync(file, "utf8")) as AuditUsersFile;
  const gotlandId = data.targets.largest_herd.genebank;
  const pick = (key: string): TestUser => {
    const u = data.users[key];
    if (!u) throw new Error(`No user "${key}" in ${file}`);
    return { username: u.username, password: u.password };
  };
  return {
    admin: pick("admin"),
    gkOwner: pick("breeder"),
    gkManager: pick(`manager_${gotlandId}`),
  };
}

// Legacy global-setup.ts uses TEST_USERS.admin, .gkOwner, .gkManager
// Map shared keys to legacy keys for backwards compatibility
export const TEST_USERS = resolveUsers();

/**
 * Log in via Flask /api/login from inside the page (HTTPS through nginx).
 */
export async function loginAs(page: Page, user: TestUser): Promise<void> {
  await page.goto(`${BASE_URL}/`, { waitUntil: "domcontentloaded" });
  const status = await page.evaluate(
    async (credentials: TestUser) => {
      const response = await fetch("/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(credentials),
        credentials: "same-origin",
      });
      return response.status;
    },
    { username: user.username, password: user.password },
  );
  if (status !== 200) {
    throw new Error(`Login failed for ${user.username}: ${status}`);
  }
}

/**
 * Log in + save browser storage state to disk (legacy — HTTPS through nginx).
 */
export async function loginAndSaveState(
  page: Page,
  context: BrowserContext,
  user: TestUser,
  statePath: string,
): Promise<void> {
  await loginAs(page, user);
  await context.storageState({ path: statePath });
}
