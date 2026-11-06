import { test, expect } from "@playwright/test";
import { dismissCookieBanner } from "./helpers/cookie-banner";

test.describe("Manager Genebank View", () => {
  test("manager can view all herds in genebank", async ({ page }) => {
    await page.goto("/genebank");
    await dismissCookieBanner(page);

    const body = page.locator("body");
    // Wait for the genebank view to load — SPA needs time for /api/user + data
    await expect(body).toContainText(/Gotland/i, { timeout: 15000 });

    // The genebank view shows individuals in a table with columns
    await expect(body).toContainText(/Nummer|Namn|Besättning/i);
  });

  test("manager can see individual details in genebank view", async ({
    page,
  }) => {
    await page.goto("/genebank");
    await dismissCookieBanner(page);

    // Wait for genebank data to load
    await expect(page.locator("body")).toContainText(/Gotland/i, {
      timeout: 15000,
    });

    // The genebank view shows individuals directly in a table
    const tableRows = page
      .locator("table tbody tr")
      .filter({ hasText: /[GM]\d+/ });

    // A genebank view with no rows is a failure, not a pass (Phase 20 Task 6,
    // brief step 2).
    await expect(tableRows.first()).toBeVisible({ timeout: 20000 });
    expect(await tableRows.count()).toBeGreaterThan(0);

    // Click first individual row
    await tableRows.first().click();
    await page.waitForLoadState("networkidle");

    // Should navigate to individual detail
    await expect(page.locator("body")).toContainText(/[GM]\d+-\d+/);
  });
});
