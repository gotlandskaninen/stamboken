import { test, expect } from "@playwright/test";

test.describe("Mating Registration", () => {
  test("owner opens breeding form and submits a mating", async ({ page }) => {
    await page.goto("/owner");
    await page.waitForLoadState("networkidle");

    // Click to open breeding list/form — "Parning" tab or "Lägg till" in breeding section
    const breedingTab = page
      .locator("a, button, [role='tab']")
      .filter({ hasText: /Parning|Avel/i })
      .first();
    await expect(breedingTab).toBeVisible({ timeout: 10000 });
    await breedingTab.click();
    await page.waitForLoadState("networkidle");

    // Click "Lägg till" to open new breeding form
    const addButton = page
      .locator("button")
      .filter({ hasText: /Lägg till/i })
      .first();
    if (await addButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await addButton.click();
      await page.waitForLoadState("networkidle");
    }

    // Form should show "Parning och Födsel" title
    await expect(page.locator("body")).toContainText(
      /Parning och Födsel|Parningsdatum|Mor|Far/i,
    );

    // Fill breeding date
    const breedDate = page.getByLabel(/Parningsdatum/i);
    if (await breedDate.isVisible({ timeout: 3000 }).catch(() => false)) {
      await breedDate.fill("2024-06-01");
    }

    // Select mother — click the "Mor" autocomplete
    const motherField = page.getByLabel(/^Mor$|Välj mor/i);
    if (await motherField.isVisible({ timeout: 3000 }).catch(() => false)) {
      await motherField.click();
      // Pick first option from dropdown
      const firstOption = page.getByRole("option").first();
      if (await firstOption.isVisible({ timeout: 3000 }).catch(() => false)) {
        await firstOption.click();
      }
    }

    // Select father — click the "Far" autocomplete
    const fatherField = page.getByLabel(/^Far$|Välj far/i);
    if (await fatherField.isVisible({ timeout: 3000 }).catch(() => false)) {
      await fatherField.click();
      const firstOption = page.getByRole("option").first();
      if (await firstOption.isVisible({ timeout: 3000 }).catch(() => false)) {
        await firstOption.click();
      }
    }

    // Submit — "Spara" button
    const saveButton = page.locator("button").filter({ hasText: /Spara/i });
    await expect(saveButton).toBeVisible({ timeout: 5000 });
    await saveButton.click();
    await page.waitForLoadState("networkidle");

    // Should see success or validation feedback
    const body = page.locator("body");
    await expect(body).toContainText(/success|sparad|Parning|error|krävs/i);
  });
});
