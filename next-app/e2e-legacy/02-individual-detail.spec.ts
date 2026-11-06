import { test, expect } from "@playwright/test";
import { dismissCookieBanner } from "./helpers/cookie-banner";

test.describe("Individual Detail Page", () => {
  test("click individual edit icon shows detail with key fields", async ({
    page,
  }) => {
    await page.goto("/owner");
    await page.waitForLoadState("networkidle");
    await dismissCookieBanner(page);

    // The legacy UI uses a table — click the edit icon (first cell) to open detail
    const table = page.locator("table[aria-label='enhanced table']");
    const rows = table.locator("tbody tr");

    // A pass on an empty herd proves nothing (Phase 20 Task 6, brief step 2):
    // the fixture herd must contain individuals.
    await expect(rows.first()).toBeVisible({ timeout: 15000 });
    expect(await rows.count()).toBeGreaterThan(0);

    // Click the edit icon in the first cell of the first row
    const editCell = rows.first().locator("td").first();
    await editCell.click();
    await page.waitForLoadState("networkidle");

    // The individual detail opens inline (URL stays at /owner or changes to /individual/)
    // Verify detail content appears — key fields like Kön, Färg, and individual number
    const body = page.locator("body");
    await expect(body).toContainText(/Kön|Färg|Besättning/i, {
      timeout: 10000,
    });
    await expect(body).toContainText(/[GM]\d+-\d+/);
  });
});
