import { test, expect, type Page } from "@playwright/test";

/**
 * The new frontend against an API with ACCESS_RULES=enforce (README, "Access
 * rules"). Needs the playwright-legacy stack: nginx, `api` (rules on), `api-test`
 * (the demo API, rules always off) with its own seeded database.
 *
 * test-gk-owner has no v2_prod_access, test-admin is promoted implicitly.
 */

const OWNER = { username: "test-gk-owner", password: "test-gk-owner-pass" };
const ADMIN = { username: "test-admin", password: "test-admin-pass" };
const BANNER_TEXT =
  "TESTMILJÖ — här kan du öva fritt. Allt återställs varje natt.";
const NOT_PROMOTED = "Ditt konto har inte tillgång till riktiga Stamboken än";

/** Sign in through the real form, so loginWithPassword sets session and sb_mode. */
async function signIn(
  page: Page,
  { username, password }: { username: string; password: string },
) {
  await page.goto("/auth/sign-in");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Logga in", exact: true }).click();
  await page.waitForURL(/\/stamboken\//, { timeout: 30000 });
}

test.describe("Access rules on the new frontend (ACCESS_RULES=enforce)", () => {
  test("account without v2_prod_access lands in demo and reads data there", async ({
    page,
  }) => {
    await signIn(page, OWNER);

    // The premise: production knows this account as not promoted.
    const me = await page.request.get("/api/user");
    expect(me.status()).toBe(200);
    expect((await me.json()).v2_prod_access).toBe(false);

    await expect(page.getByText(BANNER_TEXT)).toBeVisible();

    // The demo API answers: server-rendered rows on a page that reads data.
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 30000,
    });
  });

  test("the same account with sb_mode=prod set by hand gets no production data", async ({
    page,
    context,
  }) => {
    await signIn(page, OWNER);
    await context.addCookies([
      { name: "sb_mode", value: "prod", url: "https://localhost/" },
    ]);

    await page.goto("/stamboken/alla-kaniner");
    await expect(
      page.getByText("Kunde inte ladda kaniner. Försök igen senare."),
    ).toBeVisible();
    await expect(page.locator(".MuiDataGrid-row")).toHaveCount(0);

    // Straight to a production address under /api/v2/, with the session cookie.
    const res = await page.request.get("/api/v2/my-membership");
    expect(res.status()).toBe(403);
    expect((await res.json()).message).toBe(NOT_PROMOTED);
  });

  test("admin reads production data", async ({ page }) => {
    await signIn(page, ADMIN);

    // Admins are promoted: prod is the default mode, so no demo banner.
    await expect(page.getByText(BANNER_TEXT)).toHaveCount(0);
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 30000,
    });

    const res = await page.request.get("/api/v2/my-membership");
    expect(res.status()).not.toBe(403);
  });
});
