import { defineConfig } from "@playwright/test";

/**
 * Skärmbilder till manualen (public/stamboken/manual/) och guiden för
 * matrikeln (content/matrikel-guide/). Bilderna är Playwrights
 * jämförelsebilder (toHaveScreenshot), som workflowet skriver om med
 * --update-snapshots=all; git status visar de bilder (och därmed avsnitt) vars
 * pixlar har ändrats. Workflowet
 * manual-screenshots.yml kör dem mot den seedade CI-stacken bakom en
 * nginx-proxy; se docs/manual/README.md. Aldrig mot prod eller demo.
 */
export default defineConfig({
  testDir: "./e2e/manual",
  workers: 1,
  timeout: 120000,
  retries: 0,
  expect: {
    timeout: 20000,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      stylePath: "./e2e/manual/screenshots.css",
    },
  },
  use: {
    baseURL: process.env.MANUAL_BASE_URL || "http://localhost:8080",
    headless: true,
    deviceScaleFactor: 1,
    locale: "sv-SE",
    // A button that never becomes clickable fails fast, not at the test timeout.
    actionTimeout: 15000,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  // Playwright matches testMatch against the absolute path.
  projects: [
    {
      name: "manual",
      testMatch: /[\\/]screenshots\.spec\.ts$/,
      snapshotPathTemplate:
        "{testDir}/../../public/stamboken/manual/{arg}{ext}",
    },
    {
      name: "guide",
      testMatch: /[\\/]matrikel-guide-screenshots\.spec\.ts$/,
      snapshotPathTemplate: "{testDir}/../../content/matrikel-guide/{arg}{ext}",
    },
    // Last: its fixture adds a membership and a herd that the other pictures
    // must not show.
    {
      name: "login",
      testMatch: /[\\/]login-screenshots\.spec\.ts$/,
      snapshotPathTemplate:
        "{testDir}/../../public/stamboken/manual/{arg}{ext}",
    },
  ],
});
