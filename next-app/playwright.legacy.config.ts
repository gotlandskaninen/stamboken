import { defineConfig } from "@playwright/test";

// Default: the local-production host. Phase 20's legacy-compatibility audit
// points this at the audit stack's copy of the FINAL production hostname
// (https://stamboken.gotlandskaninen.se:18443). That name resolves to the real
// production server, so whenever it is used the browser must resolve it to
// loopback itself and ignore any configured proxy — see the launchOptions
// below and next-app/e2e-legacy/helpers/legacy-auth.ts.
const BASE_URL = process.env.LEGACY_BASE_URL ?? "https://stamboken.localhost";
const NEEDS_RESOLVER_RULES = BASE_URL.includes("gotlandskaninen.se");

export default defineConfig({
  testDir: "./e2e-legacy",
  // Output can contain real herd data when the audit stack is the target.
  outputDir: process.env.LEGACY_OUTPUT_DIR || undefined,
  // The Phase 20 audit stack carries the whole production database, so a herd
  // view that takes 2 s locally takes ~20 s there; 30 s is not enough for the
  // multi-step specs. LEGACY_TIMEOUT_MS overrides either default.
  timeout: Number(
    process.env.LEGACY_TIMEOUT_MS ??
      (NEEDS_RESOLVER_RULES ? 120000 : process.env.CI ? 60000 : 30000),
  ),
  expect: {
    timeout: NEEDS_RESOLVER_RULES ? 30000 : process.env.CI ? 15000 : 5000,
  },
  use: {
    baseURL: BASE_URL,
    ignoreHTTPSErrors: true,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
    launchOptions: NEEDS_RESOLVER_RULES
      ? {
          args: [
            "--host-resolver-rules=MAP *.gotlandskaninen.se 127.0.0.1,MAP gotlandskaninen.se 127.0.0.1",
            "--no-proxy-server",
          ],
        }
      : undefined,
  },
  retries: 1,
  projects: [
    { name: "setup", testMatch: /global-setup\.ts/ },
    {
      name: "owner-tests",
      testMatch: /0[1-8]-.*\.spec\.ts|10-.*\.spec\.ts/,
      use: { storageState: ".auth/gk-owner.json" },
      dependencies: ["setup"],
    },
    {
      name: "admin-tests",
      testMatch: /09-.*\.spec\.ts/,
      use: { storageState: ".auth/admin.json" },
      dependencies: ["setup"],
    },
    {
      name: "manager-tests",
      testMatch: /11-.*\.spec\.ts/,
      use: { storageState: ".auth/gk-manager.json" },
      dependencies: ["setup"],
    },
  ],
});
