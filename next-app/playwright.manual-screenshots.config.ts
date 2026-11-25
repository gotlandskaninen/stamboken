import { defineConfig } from "@playwright/test";

/**
 * Skärmbilder till manualen (public/stamboken/manual/) och guiden för
 * matrikeln (content/matrikel-guide/). Bilderna är Playwrights
 * jämförelsebilder (toHaveScreenshot): med --update-snapshots=changed skrivs
 * bara de som skiljer sig från bilden i repot, så git status visar vilka
 * bilder (och därmed avsnitt) som har ändrats. Workflowet
 * manual-screenshots.yml kör dem mot den seedade CI-stacken bakom en
 * nginx-proxy; se docs/manual/README.md. Aldrig mot prod eller demo.
 */
export default defineConfig({
  testDir: "./e2e/manual",
  workers: 1,
  timeout: 120000,
  retries: 0,
  expect: {
    // A changed picture is retried until this runs out before it is written.
    timeout: 8000,
    toHaveScreenshot: {
      animations: "disabled",
      caret: "hide",
      // A few pixels of anti-aliasing are not a changed screen.
      maxDiffPixels: 50,
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
      testMatch: /[\\/](?:login-)?screenshots\.spec\.ts$/,
      snapshotPathTemplate:
        "{testDir}/../../public/stamboken/manual/{arg}{ext}",
    },
    {
      name: "guide",
      testMatch: /[\\/]matrikel-guide-screenshots\.spec\.ts$/,
      snapshotPathTemplate: "{testDir}/../../content/matrikel-guide/{arg}{ext}",
    },
  ],
});
