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
// The banner's first word: DemoBanner.client.tsx writes the rest with an en dash.
const BANNER_TEXT = /TESTMILJÖ/;
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
    // The browser's list requests are blocked during the first load: if the
    // server's request went to production and failed, RabbitExplorer would
    // fetch the rows itself and hide it.
    const prodListRequests: string[] = [];
    page.on("request", (req) => {
      if (/\/api\/individuals/.test(req.url()))
        prodListRequests.push(req.url());
    });
    const browserList = /\/api(-test)?\/individuals/;
    await page.route(browserList, (route) => route.abort());
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 30000,
    });
    await page.unroute(browserList);

    // The browser's own list request, which the first render skips: it must go
    // to the demo API too, or the next search would be refused by production.
    const clientList = page.waitForResponse(/\/api-test\/individuals/, {
      timeout: 15000,
    });
    await page.locator('input[placeholder*="individnummer"]').fill("G");
    expect((await clientList).status()).toBe(200);
    expect(prodListRequests).toEqual([]);
  });

  test("the same account with sb_mode=prod set by hand gets no production data", async ({
    page,
    context,
  }) => {
    await signIn(page, OWNER);
    await context.addCookies([
      { name: "sb_mode", value: "prod", url: "https://localhost/" },
    ]);

    // The list's own request to production is the one refused, with the rules'
    // text: the error text below shows for any failure, a 502 included.
    const listRefused = page.waitForResponse(/\/api\/individuals/, {
      timeout: 30000,
    });
    await page.goto("/stamboken/alla-kaniner");
    const refused = await listRefused;
    expect(refused.status()).toBe(403);
    expect((await refused.json()).message).toBe(NOT_PROMOTED);
    await expect(
      page.getByText("Kunde inte ladda kaniner. Försök igen senare."),
    ).toBeVisible();
    await expect(page.locator(".MuiDataGrid-row")).toHaveCount(0);

    // Straight to a production address under /api/v2/, with the session cookie.
    const res = await page.request.get("/api/v2/my-membership");
    expect(res.status()).toBe(403);
    expect((await res.json()).message).toBe(NOT_PROMOTED);
  });

  // #227: a session without sb_mode (an installed app sharing the login, or a
  // cookie that expired first) follows v2_prod_access, and the cookie is set.
  for (const { user, demo } of [
    { user: ADMIN, demo: false },
    { user: OWNER, demo: true },
  ]) {
    test(`${user.username} without sb_mode lands in ${demo ? "demo" : "prod"}`, async ({
      page,
      context,
    }) => {
      await signIn(page, user);
      await context.clearCookies({ name: "sb_mode" });

      await page.goto("/stamboken/min-besattning");
      await expect(page.getByText(BANNER_TEXT)).toHaveCount(demo ? 1 : 0);
      const cookie = (await context.cookies()).find(
        (c) => c.name === "sb_mode",
      );
      expect(cookie?.value).toBe(demo ? "demo" : "prod");
    });
  }

  test("admin reads production data", async ({ page }) => {
    await signIn(page, ADMIN);

    // Admins are promoted: prod is the default mode, so no demo banner.
    await expect(page.getByText(BANNER_TEXT)).toHaveCount(0);
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 30000,
    });

    // A production address the rules guard, answered in full.
    const res = await page.request.get("/api/genebanks");
    expect(res.status()).toBe(200);
  });
});
