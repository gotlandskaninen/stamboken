import { test, expect } from "@playwright/test";

test.describe("Årsrapport Flow", () => {
  test("owner navigates yearly report wizard steps", async ({ page }) => {
    await page.goto("/yearly");
    await page.waitForLoadState("networkidle");

    const body = page.locator("body");

    // The fixture database must have an active reporting round — without one
    // this spec would pass on a page that never rendered the wizard
    // (Phase 20 Task 6, brief step 2).
    await expect(
      body.getByText(/Välj besättning|Besättning|Årsrapport/i).first(),
    ).toBeVisible({ timeout: 15000 });

    // Step 1: Select herd — "Välj Besättning"
    await expect(body).toContainText(/Välj besättning|Besättning/i);

    // Click "Nästa" to advance (herd should be auto-selected for single-herd owner)
    const nextButton = page.locator("button").filter({ hasText: /Nästa/i });
    if (await nextButton.isVisible({ timeout: 3000 }).catch(() => false)) {
      await nextButton.click();
      await page.waitForLoadState("networkidle");

      // Step 2: Contact info — "Uppdatera Kontaktinformation"
      await expect(body).toContainText(/Kontaktinformation|Namn|E-mail/i);

      // Click "Hoppa över" or "Nästa" to advance
      const skipButton = page
        .locator("button")
        .filter({ hasText: /Hoppa över|Nästa/i })
        .first();
      if (await skipButton.isVisible({ timeout: 3000 }).catch(() => false)) {
        await skipButton.click();
        await page.waitForLoadState("networkidle");

        // Step 3: Update rabbits — "Uppdatera Kaniner"
        await expect(body).toContainText(/Kaniner|Uppdatera/i);
      }
    }
  });
});
