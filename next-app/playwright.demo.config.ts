import { defineConfig } from "@playwright/test";

/**
 * Full-stack config for the 999.2 demo/prod integration specs.
 *
 * These run against the local-production stack THROUGH nginx (real `/api` and
 * `/api-test` routing + the shared Redis session from Phase 999.7) — NOT the
 * base-dev next-app on :3000, which cannot resolve the relative `/api-test`
 * route (that is nginx's job).
 *
 * We mirror `playwright.legacy.config.ts`'s `use` block (nginx host,
 * ignoreHTTPSErrors) but deliberately target `https://localhost`: the legacy
 * config's `stamboken.localhost` host serves the LEGACY React SPA, whereas the
 * v2 next-app dashboard — with the demo banner and the promoted demo/prod
 * toggle — is served at `https://localhost/stamboken/...`.
 *
 * Not part of default CI (same convention as the legacy regression suite). Run:
 *   pnpm exec playwright test --config playwright.demo.config.ts
 */
export default defineConfig({
  testDir: "./e2e",
  testMatch: /(demo-banner|promoted-toggle)\.spec\.ts/,
  timeout: 60000,
  expect: { timeout: 15000 },
  // Serial: both specs drive the same shared local-production stack and each
  // logs in as a different user in its own context; running them one at a time
  // keeps session/cookie state unambiguous.
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
