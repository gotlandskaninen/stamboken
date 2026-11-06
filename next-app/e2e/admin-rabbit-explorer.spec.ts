import { test, expect } from "@playwright/test";

// Auth is handled by storageState (admin) set in playwright.config.ts.
// Admin role is required to switch between genebanks; owners only see their own.

test.describe("Rabbit Explorer — Admin genebank toggle", () => {
  test("can switch to Mellerudskanin", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");

    // Wait for the DataGrid to load
    const rows = page.locator(".MuiDataGrid-row");
    await expect(rows.first()).toBeVisible({ timeout: 30000 });

    // First ensure we're viewing Gotlandskanin (default "Alla" may show M-numbers first)
    const gkButton = page
      .locator("button")
      .filter({ hasText: "Gotlandskanin" });
    await expect(gkButton).toBeVisible({ timeout: 5000 });
    await gkButton.click();

    // Wait for GK data — first number should be G-prefixed
    const numberCells = page.locator('.MuiDataGrid-cell[data-field="number"]');
    await expect(numberCells.first()).toContainText(/^G/, { timeout: 10000 });

    // Now switch to Mellerudskanin
    const mkButton = page
      .locator("button")
      .filter({ hasText: "Mellerudskanin" });
    await mkButton.click();

    // Wait for MK data — first number should change to M-prefixed
    await expect(numberCells.first()).toContainText(/^M/, { timeout: 10000 });
  });
});
