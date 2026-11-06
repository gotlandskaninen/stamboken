import { test, expect } from "@playwright/test";
import { loginInline } from "../e2e-shared/auth";

test.describe("Breeding List — /min-besattning?tab=breeding", () => {
  test("loads with breeding records and parent names", async ({ page }) => {
    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });

    // Seed data: G1274 has breedings with parents Visby Stamfar × Visby Stammor (2021)
    // and Fårö Grundare × Visby Vilda (2023).
    // The component renders mother_name and father_name as link text.
    await expect(
      page.getByText(/Visby Stamfar|Visby Stammor/).first(),
    ).toBeVisible({ timeout: 60000 });
  });

  test("shows year group headers", async ({ page }) => {
    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });

    // Wait for content to load first
    await expect(
      page.getByText(/Visby Stamfar|Visby Stammor/).first(),
    ).toBeVisible({ timeout: 60000 });

    // Year headers carry data-testid="year-heading" (B4). The leading
    // "Pågående parningar" heading shares the testid — assert inclusion,
    // not an exact set.
    const yearHeaders = page.locator('[data-testid="year-heading"]');
    const headerTexts = await yearHeaders.allTextContents();
    expect(headerTexts).toContain("2021");
    expect(headerTexts).toContain("2023");
  });

  test("empty herd shows empty state", async ({ page, context }) => {
    // Switch to test-empty user (owner of G1500, no breedings)
    await loginInline(page, context, {
      username: "test-empty",
      password: "test-empty-pass",
    });

    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });

    await expect(
      page.getByText("Inga kullar eller parningar registrerade ännu."),
    ).toBeVisible({ timeout: 60000 });
  });
});
