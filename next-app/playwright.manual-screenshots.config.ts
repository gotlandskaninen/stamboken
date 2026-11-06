import { defineConfig } from "@playwright/test";

/**
 * Skärmbilder till docs/USER_MANUAL.md (docs/manual/*.png). Körs för hand mot
 * den seedade e2e-stacken bakom en nginx-proxy (se docs/manual/README.md),
 * aldrig i CI och aldrig mot prod eller demo:
 *
 *   pnpm exec playwright test --config playwright.manual-screenshots.config.ts
 */
export default defineConfig({
  testDir: "./e2e/manual",
  testMatch: /screenshots\.spec\.ts/,
  workers: 1,
  timeout: 120000,
  retries: 0,
  use: {
    baseURL: process.env.MANUAL_BASE_URL || "http://localhost:8080",
    headless: true,
    deviceScaleFactor: 1,
    locale: "sv-SE",
  },
});
