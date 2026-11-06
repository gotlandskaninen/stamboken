import { test, expect } from "@playwright/test";

test.describe("Litter Registration", () => {
  test("owner opens existing breeding and registers birth", async ({
    page,
  }) => {
    await page.goto("/owner");
    await page.waitForLoadState("networkidle");

    // Navigate to breeding list
    const breedingTab = page
      .locator("a, button, [role='tab']")
      .filter({ hasText: /Parning|Avel/i })
      .first();
    await expect(breedingTab).toBeVisible({ timeout: 10000 });
    await breedingTab.click();
    await page.waitForLoadState("networkidle");

    // Click on an existing breeding row to open its form
    const breedingRow = page.locator("tr, [role='row']").nth(1);
    if (await breedingRow.isVisible({ timeout: 5000 }).catch(() => false)) {
      await breedingRow.click();
      await page.waitForLoadState("networkidle");

      // The breeding form should show birth fields
      const body = page.locator("body");
      await expect(body).toContainText(/Födelsedatum|Kullstorlek|Födsel/i);

      // Fill birth date
      const birthDate = page.getByLabel(/Födelsedatum/i).last();
      if (await birthDate.isVisible({ timeout: 3000 }).catch(() => false)) {
        await birthDate.fill("2024-07-15");
      }

      // Fill litter size
      const litterSize = page.getByLabel(/Kullstorlek/i).first();
      if (await litterSize.isVisible({ timeout: 3000 }).catch(() => false)) {
        await litterSize.fill("5");
      }

      // Save
      const saveButton = page.locator("button").filter({ hasText: /Spara/i });
      await expect(saveButton).toBeVisible({ timeout: 5000 });
      await saveButton.click();
      await page.waitForLoadState("networkidle");
    }
  });
});
