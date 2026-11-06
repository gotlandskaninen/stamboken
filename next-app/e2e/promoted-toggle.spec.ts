import { test, expect, type Page } from "@playwright/test";

/**
 * Full-stack (nginx + api + api-test, shared Redis session from Phase 999.7).
 * Run with the dedicated demo config (NOT part of default CI):
 *   pnpm exec playwright test --config playwright.demo.config.ts promoted-toggle.spec.ts
 *
 * A promoted user (test-gk-owner-promoted, v2_prod_access=True — seeded by
 * cli/create_test_users, Plan 05) defaults to PROD on login (no banner), and
 * gets a demo/prod toggle in the user menu (user-approved terminology: demo is
 * "testmiljön", prod is "riktiga stamboken"). Clicking the toggle opens a
 * confirmation dialog — "Avbryt" must leave the mode unchanged; confirming must
 * switch to demo WITHOUT a re-login. On /stamboken/alla-kaniner both fetch
 * paths — the server-rendered initial data (fetchApi) and a client interaction
 * (RTK Query) — must resolve against the SAME backend (Pitfall 1: no prod-data
 * flash in demo).
 */

const BANNER_TEXT =
  "TESTMILJÖ — här kan du öva fritt. Allt återställs varje natt.";
const PROMOTED = {
  username: "test-gk-owner-promoted",
  password: "test-gk-owner-promoted-pass",
};

/** Log in through the real v2 sign-in form so loginWithPassword sets sb_mode. */
async function signIn(page: Page, username: string, password: string) {
  await page.goto("/auth/sign-in");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  // exact: true — the Google Identity button ("Logga in med Google...") also
  // matches a substring "Logga in" when it happens to render.
  await page.getByRole("button", { name: "Logga in", exact: true }).click();
  await page.waitForURL(/\/stamboken\//, { timeout: 30000 });
}

test.describe("Promoted user — prod default + demo/prod toggle", () => {
  test("defaults to prod, flips to demo without re-login, both paths agree", async ({
    page,
  }) => {
    await signIn(page, PROMOTED.username, PROMOTED.password);

    // Prod default: NO demo banner on login.
    await expect(page.getByText(BANNER_TEXT)).toHaveCount(0);

    // The promoted-only toggle is present in the user menu (new terminology).
    await page.getByRole("button", { name: "Account" }).click();
    const toggle = page.getByRole("menuitem", { name: "Byt till testmiljön" });
    await expect(toggle).toBeVisible();

    // Clicking it opens a confirmation dialog — "Avbryt" must close it and
    // leave the mode unchanged (no banner appears, no reload needed).
    await toggle.click();
    const dialog = page.getByRole("dialog", { name: "Byta till testmiljön?" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Avbryt" }).click();
    await expect(dialog).toHaveCount(0);
    await expect(page.getByText(BANNER_TEXT)).toHaveCount(0);

    // Now flip to demo for real: re-open the menu, click the toggle and
    // CONFIRM. The banner must appear WITHOUT bouncing through the sign-in
    // page (setMode + router.refresh re-reads the mode server-side; no
    // re-authentication).
    await page.getByRole("button", { name: "Account" }).click();
    await page.getByRole("menuitem", { name: "Byt till testmiljön" }).click();
    await page
      .getByRole("dialog", { name: "Byta till testmiljön?" })
      .getByRole("button", { name: "Ja, byt till testmiljön" })
      .click();
    await expect(page.getByText(BANNER_TEXT)).toBeVisible({ timeout: 15000 });
    expect(page.url()).not.toContain("/auth/sign-in");
    expect(page.url()).toContain("/stamboken/");

    // Pitfall 1 — two-path agreement on /stamboken/alla-kaniner in demo mode.
    // Record every browser-side /individuals request and split it by backend:
    // nginx routes /api-test/* → api-test (demo), /api/* → api (prod). The
    // server-side fetchApi() request is server-to-server and never appears here;
    // its success is proven by the initial rows rendering below.
    const demoReqs: string[] = [];
    const prodReqs: string[] = [];
    page.on("request", (req) => {
      const u = req.url();
      if (/\/api-test\/individuals/.test(u)) demoReqs.push(u);
      else if (/\/api\/individuals/.test(u)) prodReqs.push(u);
    });

    await page.goto("/stamboken/alla-kaniner");

    // Server-rendered initial data (fetchApi routed to the demo backend and the
    // shared 999.7 session was valid on api-test) — rows are visible.
    const rows = page.locator(".MuiDataGrid-row");
    await expect(rows.first()).toBeVisible({ timeout: 30000 });

    // Client interaction: typing in the search box fires the RTK Query
    // (browser) path. It must hit the DEMO backend, matching the server path.
    const clientDemoReq = page.waitForRequest(/\/api-test\/individuals/, {
      timeout: 15000,
    });
    await page.locator('input[placeholder*="individnummer"]').fill("G");
    await clientDemoReq;

    // No prod /individuals request happened on this demo page — i.e. no
    // prod-data flash after interacting (the Pitfall 1 regression).
    expect(
      prodReqs,
      `unexpected prod /api/individuals requests in demo mode: ${prodReqs.join(", ")}`,
    ).toHaveLength(0);
    expect(demoReqs.length).toBeGreaterThan(0);

    // CR-01 regression: switching back to prod must purge the RTK Query cache
    // (resetApiState) so the already-mounted table refetches from the PROD
    // backend on the SAME page — no hard reload. Without the reset, the cached
    // demo rows for these query args would be served under prod mode.
    const clientProdReq = page.waitForRequest(/\/api\/individuals/, {
      timeout: 15000,
    });
    await page.getByRole("button", { name: "Account" }).click();
    await page
      .getByRole("menuitem", { name: "Byt till riktiga stamboken" })
      .click();
    await page
      .getByRole("dialog", { name: "Byta till riktiga stamboken?" })
      .getByRole("button", { name: "Ja, byt till riktiga stamboken" })
      .click();
    await clientProdReq;
    // Back in prod: banner gone, still on the same dashboard page (no re-login).
    await expect(page.getByText(BANNER_TEXT)).toHaveCount(0, {
      timeout: 15000,
    });
    expect(page.url()).not.toContain("/auth/sign-in");
    expect(page.url()).toContain("/stamboken/alla-kaniner");
  });
});
