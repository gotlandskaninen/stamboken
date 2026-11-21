import { defineConfig } from "@playwright/test";

/**
 * The new frontend in a browser with ACCESS_RULES=enforce on `api` and the demo
 * API (`api-test`) present. Runs in the playwright-legacy job, whose stack has
 * both, against https://localhost (the new frontend; the legacy frontend is on
 * stamboken.localhost, the only name in that job's LEGACY_HOSTS).
 *
 *   pnpm exec playwright test --config playwright.access.config.ts
 */
export default defineConfig({
  testDir: "./e2e-access",
  timeout: 60000,
  expect: { timeout: 15000 },
  workers: 1,
  use: {
    baseURL: "https://localhost",
    ignoreHTTPSErrors: true,
    headless: true,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },
  retries: 1,
});
