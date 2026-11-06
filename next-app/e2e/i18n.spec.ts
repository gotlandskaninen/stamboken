import { test, expect } from "@playwright/test";

// Helper: land on the dashboard and wait for the topbar nav to render.
async function waitForTopbar(page: import("@playwright/test").Page) {
  await page.goto("/stamboken/min-besattning", { waitUntil: "networkidle" });
  await expect(page.getByText("Min besättning").first()).toBeVisible({
    timeout: 15000,
  });
}

test.describe("i18n - default Swedish language", () => {
  test("html lang attribute is sv by default", async ({ page }) => {
    await page.goto("/stamboken/min-besattning");
    expect(await page.locator("html").getAttribute("lang")).toBe("sv");
  });

  test("topbar shows Swedish labels by default", async ({ page }) => {
    await waitForTopbar(page);
    await expect(page.getByText("Min besättning").first()).toBeVisible();
    await expect(page.getByText("Genetik").first()).toBeVisible();
    await expect(page.getByText("Profil").first()).toBeVisible();
  });
});

test.describe("i18n - language switching (SV/EN toggle)", () => {
  test("toggle switches the topbar labels to English", async ({ page }) => {
    await waitForTopbar(page);

    // The new two-state toggle: from SV it switches straight to EN (no menu).
    await page.getByRole("button", { name: /Byt språk till engelska/ }).click();

    await expect(page.getByText("My Herd").first()).toBeVisible();
    await expect(page.getByText("Genetics").first()).toBeVisible();
    await expect(page.getByText("Profile").first()).toBeVisible();
  });
});
