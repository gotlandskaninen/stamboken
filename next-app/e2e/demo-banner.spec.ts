import { test, expect, type Page } from "@playwright/test";
import { TEST_USERS } from "../e2e-shared/auth";

/**
 * Full-stack (nginx + api + api-test, shared Redis session from Phase 999.7).
 * Run with the dedicated demo config (NOT part of default CI):
 *   pnpm exec playwright test --config playwright.demo.config.ts demo-banner.spec.ts
 *
 * A non-promoted user (test-gk-owner, v2_prod_access=false) logging into the v2
 * stamboken defaults to DEMO — local-production sets API_TEST_INTERNAL_URL, so
 * `initialMode()` (actions.ts) resolves demo for non-promoted accounts. The
 * unmissable demo banner must therefore render, it must have no dismiss control,
 * and the user menu must NOT expose the promoted-only demo/prod toggle.
 */

// Exact copy of DemoBanner.client.tsx's text. User-approved terminology: demo
// mode is "testmiljön" in UI copy (supersedes the plan's original
// "raderas varje natt" wording — recorded as a checkpoint-feedback deviation).
const BANNER_TEXT =
  "TESTMILJÖ — här kan du öva fritt. Allt återställs varje natt.";

/** Log in through the real v2 sign-in form so loginWithPassword sets sb_mode. */
async function signIn(page: Page, username: string, password: string) {
  await page.goto("/auth/sign-in");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  // exact: true — the Google Identity button ("Logga in med Google...") also
  // matches a substring "Logga in" when it happens to render.
  await page.getByRole("button", { name: "Logga in", exact: true }).click();
  // loginWithPassword() redirects to /stamboken/min-besattning on success.
  await page.waitForURL(/\/stamboken\//, { timeout: 30000 });
}

test.describe("Demo banner — non-promoted user", () => {
  test("sees the unmissable demo banner and has no demo/prod toggle", async ({
    page,
  }) => {
    const { username, password } = TEST_USERS.owner; // test-gk-owner (non-promoted)
    await signIn(page, username, password);

    // The demo banner is visible.
    const banner = page.getByText(BANNER_TEXT);
    await expect(banner).toBeVisible();

    // ...and unmissable: the DemoBanner MUI Alert carries no dismiss/close
    // control (contrast the dismissible WipBanner rendered right after it).
    const bannerAlert = page.locator(".MuiAlert-root", {
      hasText: BANNER_TEXT,
    });
    await expect(bannerAlert.locator("button")).toHaveCount(0);

    // Open the user dropdown — a non-promoted user must NOT see the mode toggle.
    await page.getByRole("button", { name: "Account" }).click();
    // Menu is open (a known item is visible)...
    await expect(
      page.getByRole("menuitem", { name: "Logga ut" }),
    ).toBeVisible();
    // ...and it carries no demo/prod toggle (new terminology).
    await expect(
      page.getByRole("menuitem", {
        name: /Byt till (testmiljön|riktiga stamboken)/,
      }),
    ).toHaveCount(0);
  });
});
