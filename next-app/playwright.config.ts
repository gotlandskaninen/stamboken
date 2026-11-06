import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  // The e2e/admin/* specs need a bootstrap-local-production stack (they
  // docker-exec psql against docker-compose.local-production.yml and require a
  // prod-mode admin session) — they run ONLY via playwright.admin.config.ts,
  // never in this default CI config. Ignored globally here; owner-tests below
  // overrides testIgnore, so it repeats the admin-dir exclusion in its array.
  // e2e/manual/screenshots.spec.ts skriver docs/manual/*.png och körs bara via
  // playwright.manual-screenshots.config.ts; mutation-manual-flows.spec.ts i
  // samma mapp hör till mutation-tests nedan.
  testIgnore: [/e2e\/admin\//, /e2e\/manual\/screenshots\.spec\.ts$/],
  workers: process.env.CI ? 2 : undefined,
  timeout: process.env.CI ? 60000 : 30000,
  expect: { timeout: process.env.CI ? 15000 : 5000 },
  use: {
    baseURL: "http://localhost:3000",
    headless: true,
    screenshot: "only-on-failure",
    trace: "on-first-retry",
  },
  retries: 1,
  // Playwright matches these against the ABSOLUTE path, so anchor them to the
  // file name: a checkout under e.g. ".../stamboken-del-public-flows-…/" must not
  // turn every spec into a public (anonymous) test.
  projects: [
    {
      name: "setup",
      testMatch: /global-setup\.ts/,
    },
    {
      name: "owner-tests",
      // demo-banner/promoted-toggle need the local-production stack (api-test +
      // demo DB) — run via playwright.demo.config.ts, never in this CI config.
      // e2e/admin/* likewise runs only via playwright.admin.config.ts (repeats
      // the global testIgnore because a project-level testIgnore overrides it).
      testIgnore: [
        /[\\/](?:(?:admin|manager|mutation|public)-[^\\/]*|demo-banner|promoted-toggle)\.spec\.ts$/,
        /e2e\/admin\//,
        /e2e\/manual\/screenshots\.spec\.ts$/,
      ],
      use: { storageState: "e2e/.auth/gk-owner.json" },
      dependencies: ["setup"],
    },
    {
      name: "public-tests",
      testMatch: /[\\/]public-[^\\/]*\.spec\.ts$/,
      // No storageState, no setup dependency — genuinely anonymous.
    },
    {
      name: "mutation-tests",
      testMatch: /[\\/]mutation-[^\\/]*\.spec\.ts$/,
      use: { storageState: "e2e/.auth/gk-owner.json" },
      fullyParallel: false,
      // Each mutation file uses distinct parent pairs (no shared data),
      // so parallel file execution is safe. fullyParallel:false ensures
      // tests within each file run serially.
      dependencies: ["setup"],
    },
    {
      name: "admin-tests",
      testMatch: /[\\/]admin-[^\\/]*\.spec\.ts$/,
      use: { storageState: "e2e/.auth/admin.json" },
      dependencies: ["setup"],
    },
    {
      name: "manager-tests",
      testMatch: /[\\/]manager-[^\\/]*\.spec\.ts$/,
      use: { storageState: "e2e/.auth/gk-manager.json" },
      dependencies: ["setup"],
    },
  ],
  webServer: {
    command: "pnpm dev",
    port: 3000,
    reuseExistingServer: true,
    timeout: 120000,
    env: {
      ...process.env,
      API_INTERNAL_URL: process.env.API_INTERNAL_URL || "http://localhost:9090",
    },
  },
});
