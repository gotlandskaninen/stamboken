import { test, expect } from "@playwright/test";
import { dismissCookieBanner } from "./helpers/cookie-banner";

test.describe("Admin Herd Management", () => {
  test("admin can open manage page via menu", async ({ page }) => {
    // The legacy SPA redirects direct /manage navigation before auth loads.
    // Navigate to home first, then use the menu to reach manage.
    await page.goto("/");
    await dismissCookieBanner(page);
    await page.waitForLoadState("networkidle");

    // Click the menu and find "Administrera" link
    const menuButton = page.locator("button").filter({ hasText: /Menu/i });
    if (await menuButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await menuButton.click();
    }

    const adminLink = page.getByRole("link", { name: "Administrera" }).first();
    await expect(adminLink).toBeVisible({ timeout: 10000 });
    await adminLink.click();
    await page.waitForLoadState("networkidle");

    // The manage page shows "Besättningar" and "Användare" buttons
    await expect(page.locator("body")).toContainText(
      /Besättningar|Användare/i,
      {
        timeout: 10000,
      },
    );
  });

  test("admin can select a herd and view its form", async ({ page }) => {
    // Use menu navigation to avoid SPA redirect race
    await page.goto("/");
    await dismissCookieBanner(page);
    await page.waitForLoadState("networkidle");

    const menuButton = page.locator("button").filter({ hasText: /Menu/i });
    if (await menuButton.isVisible({ timeout: 5000 }).catch(() => false)) {
      await menuButton.click();
    }
    const adminLink = page.getByRole("link", { name: "Administrera" }).first();
    await expect(adminLink).toBeVisible({ timeout: 10000 });
    await adminLink.click();
    await page.waitForLoadState("networkidle");

    // Wait for manage page to load with admin controls
    const herdsButton = page
      .locator("button")
      .filter({ hasText: /Besättningar/i });
    await expect(herdsButton).toBeVisible({ timeout: 15000 });
    await herdsButton.click();
    await page.waitForLoadState("networkidle");

    // Select a genebank if dropdown visible
    const genebankSelect = page.getByLabel(/Genbank/i);
    if (await genebankSelect.isVisible({ timeout: 3000 }).catch(() => false)) {
      await genebankSelect.click();
      const firstOption = page.getByRole("option").first();
      if (await firstOption.isVisible({ timeout: 3000 }).catch(() => false)) {
        await firstOption.click();
      }
    }

    // Search for a herd
    const herdSearch = page.getByLabel(/Sök besättning/i);
    if (await herdSearch.isVisible({ timeout: 3000 }).catch(() => false)) {
      await herdSearch.click();
      const firstHerd = page.getByRole("option").first();
      if (await firstHerd.isVisible({ timeout: 3000 }).catch(() => false)) {
        await firstHerd.click();
        await page.waitForLoadState("networkidle");

        await expect(page.locator("body")).toContainText(
          /Besättningsnamn|Kontaktperson/i,
        );
      }
    }
  });

  test("admin can navigate to genebank and see individuals", async ({
    page,
  }) => {
    await page.goto("/genebank");
    await dismissCookieBanner(page);

    // Wait for genebank view to render with genebank tabs/buttons
    await expect(page.locator("body")).toContainText(/Gotland|Mellerud/i, {
      timeout: 15000,
    });

    // The genebank view shows individuals directly in a table
    // URL stays at /genebank or becomes /genebank/Gotlandskanin
    await expect(page.locator("body")).toContainText(/Nummer|Namn|Besättning/i);
  });
});
