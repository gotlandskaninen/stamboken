import { defineConfig } from "@playwright/test";

/**
 * Phase 17 Adminpanel E2E suite (spec §7.3 — 19 specs).
 *
 * Runs against the LOCAL-PRODUCTION stack through nginx (real /api routing,
 * shared Redis sessions from Phase 999.7, migration 27→28 applied on API
 * start). NOT the base-dev stack on :3000/:9090 — the admin panel is
 * prod-mode-only and the mass-logout endpoint needs the real Redis
 * session store. Bring the stack up first:
 *
 *   bootstrap-local-production.sh   # lives in stamboken-drift
 *   cd next-app && pnpm exec playwright test --config playwright.admin.config.ts
 *
 * Not part of default CI — same convention as playwright.legacy.config.ts
 * and playwright.demo.config.ts.
 *
 * ORDERING IS LOAD-BEARING: Playwright discovers spec files alphabetically
 * and `workers: 1` makes execution strictly serial in that order. The
 * two-digit filename prefixes encode the required order:
 *   - 01–04 access gates first (spec §7.3: "written first — biggest
 *     correctness risk"),
 *   - 21-massutloggning.spec.ts LAST — it SCAN+DELetes every session in
 *     Redis db 2, killing the session of any test that would run after it.
 *     Never add a spec with a prefix above 21 without renumbering mass
 *     logout to stay last.
 */
export default defineConfig({
  testDir: "./e2e/admin",
  testMatch: /\d{2}-.*\.spec\.ts/,
  timeout: 60000,
  expect: { timeout: 15000 },
  workers: 1,
  fullyParallel: false,
  retries: 1,
  globalSetup: "./e2e/admin/global-setup.ts",
  use: {
    baseURL: "https://localhost",
    ignoreHTTPSErrors: true,
    headless: true,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
    // Belt to ignoreHTTPSErrors: the per-context bypass intermittently
    // fails on the first page.goto after a page.request login (reproduced
    // 15/15 with the loginAs sequence, 0/20 without — Playwright 1.58).
    // The launch-level flag covers the whole browser; self-signed
    // localhost only, this config never runs in CI.
    launchOptions: { args: ["--ignore-certificate-errors"] },
  },
});
