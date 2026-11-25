import { test, expect } from "@playwright/test";

// The made-up atlas package from `flask seed create` (cli/seed.py, _fargatlas_paket): a made-up key with three
// groups, and generated photos for 11, 22, 31, 42 and 100, none for the others. Auth: storageState gk-owner (playwright.config.ts).

test.describe("Färgatlas", () => {
  test("grupperna, ett foto och Foto saknas", async ({ page }) => {
    await page.goto("/stamboken/fargatlas");
    await expect(
      page.getByRole("heading", { level: 1, name: "Färgatlas" }),
    ).toBeVisible();
    await expect(
      page.getByRole("main").getByRole("heading", { level: 2 }),
    ).toHaveCount(4); // the seed key's three groups and Övriga färger

    const vilt = page.getByRole("region", { name: "Testgrupp vilt" });
    const viltgra = vilt.locator("#farg-22");
    await expect(
      viltgra.getByRole("heading", { name: "22 Viltgrå" }),
    ).toBeVisible();
    const img = viltgra.getByRole("img");
    await img.scrollIntoViewIfNeeded();
    await expect
      .poll(() => img.evaluate((el: HTMLImageElement) => el.naturalWidth))
      .toBeGreaterThan(0);
    await expect(viltgra.getByText(/Foto: Test Fotograf/)).toBeVisible();
    await expect(
      vilt.locator("#farg-24").getByText("Foto saknas"),
    ).toBeVisible();
  });

  test("ett atlasfoto lämnas inte ut utan inloggning", async ({
    page,
    playwright,
    baseURL,
  }) => {
    const url = "/api/v2/fargatlas/foto/22-a?storlek=480";
    const loggedIn = await page.request.get(url);
    expect(loggedIn.status()).toBe(200);
    expect(loggedIn.headers()["cache-control"]).toBe("private, max-age=86400");

    const anonymous = await playwright.request.newContext({
      baseURL,
      storageState: { cookies: [], origins: [] },
    });
    expect((await anonymous.get(url)).status()).toBe(401);
    expect((await anonymous.get("/api/v2/fargatlas")).status()).toBe(401);
    await anonymous.dispose();
  });
});
