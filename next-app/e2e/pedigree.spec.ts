import { test, expect } from "@playwright/test";

// Seed data: G1274-2311 "Visby Junior" has 2 generations of known ancestors:
//   Mother: G1274-2112 "Visby Vilda" (parents: G1274-1911 + G1274-1921)
//   Father: G1398-2011 "Fårö Grundare" (no parents — founders)
// Auth is handled by storageState (gk-owner) set in playwright.config.ts.

const INDIVIDUAL = "G1274-2311";

test.describe("Pedigree tree visualization", () => {
  test("renders 3-generation pedigree tree with known ancestors", async ({
    page,
  }) => {
    await page.goto(`/stamboken/individ/${INDIVIDUAL}`);

    const tree = page.locator('[data-testid="pedigree-tree"]');
    await expect(tree).toBeVisible({ timeout: 15000 });

    // Mother
    await expect(tree.getByText("G1274-2112")).toBeVisible();
    // Father
    await expect(tree.getByText("G1398-2011")).toBeVisible();
    // Maternal grandparents (Visby Vilda's parents)
    await expect(tree.getByText("G1274-1911")).toBeVisible();
    await expect(tree.getByText("G1274-1921")).toBeVisible();
  });

  test("clicking ancestor navigates to their page", async ({ page }) => {
    await page.goto(`/stamboken/individ/${INDIVIDUAL}`);

    const tree = page.locator('[data-testid="pedigree-tree"]');
    await expect(tree).toBeVisible({ timeout: 15000 });

    // Click the mother node and verify navigation
    const motherNode = tree.locator('a[href="/stamboken/individ/G1274-2112"]');
    await expect(motherNode).toBeVisible();
    await motherNode.click();
    await page.waitForURL(/\/stamboken\/individ\/G1274-2112/, {
      timeout: 15000,
    });
    expect(page.url()).toContain("/stamboken/individ/G1274-2112");
  });

  test("missing ancestor shows 'Okänd'", async ({ page }) => {
    await page.goto(`/stamboken/individ/${INDIVIDUAL}`);

    const tree = page.locator('[data-testid="pedigree-tree"]');
    await expect(tree).toBeVisible({ timeout: 15000 });

    // Father (Fårö Grundare) has no parents → grandparent cells show "Okänd"
    const unknownNodes = tree.getByText("Okänd");
    await expect(unknownNodes.first()).toBeVisible();
  });

  test("375px viewport: tree is scrollable and nodes readable", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 667 });
    await page.goto(`/stamboken/individ/${INDIVIDUAL}`);

    const tree = page.locator('[data-testid="pedigree-tree"]');
    await expect(tree).toBeVisible({ timeout: 15000 });

    // The tree container should be scrollable (parent has overflow-x: auto)
    const scrollContainer = tree.locator("..");
    const scrollWidth = await scrollContainer.evaluate((el) => el.scrollWidth);
    const clientWidth = await scrollContainer.evaluate((el) => el.clientWidth);
    expect(scrollWidth).toBeGreaterThan(clientWidth);

    // Parent node should still be readable
    await expect(tree.getByText("G1274-2112").first()).toBeVisible();
  });
});
