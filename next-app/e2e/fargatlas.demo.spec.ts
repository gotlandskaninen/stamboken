import { test, expect, type Page } from "@playwright/test";
import { TEST_USERS } from "../e2e-shared/auth";

/**
 * Full stack (nginx, api and api-test), with the demo config (not part of default CI):
 *   docker compose -f docker-compose.local-production.yml exec api-test flask seed fargatlas
 *   pnpm exec playwright test --config playwright.demo.config.ts fargatlas.demo.spec.ts
 *
 * test-gk-owner is not promoted, so the login lands in test mode. Production refuses a session the demo API made,
 * so the atlas and its photos must come from api-test, where the seed put the made-up package too.
 */

async function signIn(page: Page, username: string, password: string) {
  await page.goto("/auth/sign-in");
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(password);
  await page.getByRole("button", { name: "Logga in", exact: true }).click();
  await page.waitForURL(/\/stamboken\//, { timeout: 30000 });
}

test("en demosession ser färgatlasen med foto från api-test", async ({
  page,
}) => {
  const { username, password } = TEST_USERS.owner;
  await signIn(page, username, password);

  const photo = page.waitForResponse((r) =>
    r.url().includes("/v2/fargatlas/foto/"),
  );
  await page.goto("/stamboken/fargatlas");
  await expect(
    page.getByRole("main").getByRole("heading", { level: 2 }),
  ).toHaveCount(4); // the seed key's three groups and Övriga färger
  const img = page.locator("#farg-22").getByRole("img");
  await img.scrollIntoViewIfNeeded();
  const response = await photo;
  expect(new URL(response.url()).pathname).toMatch(
    /^\/api-test\/v2\/fargatlas\/foto\//,
  );
  expect(response.status()).toBe(200);
  await expect
    .poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth))
    .toBeGreaterThan(0);
});
