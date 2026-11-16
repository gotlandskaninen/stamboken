import { test, expect } from "@playwright/test";

// The matrikel guide is for those who keep the member register: admins and
// matrikel admins read it. Other logged-in users get a 404 for the page and
// its screenshots (they live outside public/); visitors who are not logged in
// are sent to sign in, as on every page under /medlem.

test("an admin reads the guide, its pictures and its anchors", async ({
  page,
}) => {
  await page.goto("/medlem/matrikel");
  await page.getByRole("link", { name: "Guide", exact: true }).click();
  await expect(page).toHaveURL(/\/medlem\/guide$/);
  await expect(
    page.getByRole("heading", { level: 1, name: "Guide för matrikeln" }),
  ).toBeVisible();

  const shot = page.getByRole("img", { name: "Matrikeln" });
  await shot.scrollIntoViewIfNeeded();
  await expect
    .poll(() => shot.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);

  const missing = await page.evaluate(() =>
    [...document.querySelectorAll<HTMLAnchorElement>('article a[href^="#"]')]
      .map((a) => a.hash.slice(1))
      .filter((hash) => !document.getElementById(decodeURIComponent(hash))),
  );
  expect(missing).toEqual([]);
});

test.describe("a breeder", () => {
  test.use({ storageState: "e2e/.auth/gk-owner.json" });

  test("gets 404 for the guide and its pictures", async ({ page, request }) => {
    const res = await page.goto("/medlem/guide");
    expect(res?.status()).toBe(404);
    expect(
      (await request.get("/medlem/guide/bild/matrikel.png")).status(),
    ).toBe(404);
  });
});

test.describe("someone not logged in", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("is sent to sign in for the guide, and gets 404 for its pictures", async ({
    page,
    request,
  }) => {
    // Like every page under /medlem: the middleware asks for a login first.
    await page.goto("/medlem/guide");
    await expect(page).toHaveURL(/\/auth\/sign-in/);
    expect(
      (await request.get("/medlem/guide/bild/matrikel.png")).status(),
    ).toBe(404);
  });
});
