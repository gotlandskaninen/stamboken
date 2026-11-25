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
    ).toHaveCount(5); // Hjälp mig välja, the seed key's three groups and Övriga färger

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
    // without a photo the card has no image area
    await expect(vilt.locator("#farg-24").getByRole("img")).toHaveCount(0);

    // the index jumps to a number
    await page.getByLabel("Gå till nummer").selectOption("24");
    await expect(page).toHaveURL(/#farg-24$/);
  });

  test("Hjälp mig välja leder till 22 Viltgrå", async ({ page }) => {
    await page.goto("/stamboken/fargatlas");
    const guide = page.getByRole("region", { name: "Hjälp mig välja" });
    // the made-up key of the seed's package
    for (const svar of ["Nej", "Ja, testviltfärg"]) {
      await guide.getByRole("button", { name: new RegExp(`^${svar}`) }).click();
    }
    await expect(
      guide.getByRole("heading", { name: "22 Viltgrå" }),
    ).toBeVisible();
    await guide
      .getByRole("group", { name: /pälsen/ })
      .getByRole("button", { name: "Ja", exact: true })
      .click();
    await expect(guide.getByText(/välj Rex vid Päls/)).toBeVisible();
    await guide.getByRole("button", { name: "Tillbaka" }).click();
    await expect(
      guide.getByRole("button", { name: /^Ja, testviltfärg/ }),
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
