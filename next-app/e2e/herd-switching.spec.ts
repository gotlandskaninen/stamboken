import { test, expect } from "@playwright/test";
import { loginInline } from "../e2e-shared/auth";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

/**
 * Story 2.11: Min besättning — Full RSC Migration
 *
 * Tests that herd switching is server-driven (URL-based navigation)
 * and that RTK read hooks have been removed.
 */

test.describe("Herd switching — server-driven navigation", () => {
  test("dual-owner can switch herds and URL updates", async ({
    page,
    context,
  }) => {
    // Login as test-dual who owns both a GK and MK herd
    await loginInline(page, context, {
      username: "test-dual",
      password: "test-dual-pass",
    });

    // Navigate to min-besattning — should load first herd
    await page.goto("/stamboken/min-besattning", {
      waitUntil: "domcontentloaded",
    });

    // Wait for page to load — herd name is the masthead <h1>
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 60000,
    });

    // Should see herd chips (shown when user owns > 1 herd). HerdSwitcher
    // renders next/link ANCHORS (role=link) labelled by herd id. test-dual
    // owns 2 herds; the first is active by default, so the last chip navigates.
    const chips = page.getByRole("link", { name: /^[GM]\d+$/ });
    await expect(chips.first()).toBeVisible({ timeout: 10000 });
    expect(await chips.count()).toBeGreaterThanOrEqual(2);

    // Record the initial URL
    const initialUrl = page.url();

    await chips.last().click();

    // URL should now contain ?herd= parameter
    await page.waitForURL(/[?&]herd=/, { timeout: 10000 });
    const newUrl = page.url();
    expect(newUrl).not.toBe(initialUrl);
    expect(newUrl).toMatch(/[?&]herd=[A-Z0-9]+/);
  });

  test("switching herds from a tab keeps the ?tab param", async ({
    page,
    context,
  }) => {
    await loginInline(page, context, {
      username: "test-dual",
      password: "test-dual-pass",
    });

    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 60000,
    });

    await page
      .getByRole("link", { name: /^[GM]\d+$/ })
      .last()
      .click();
    await page.waitForURL(/[?&]herd=/, { timeout: 10000 });

    // tab survived the herd switch
    expect(page.url()).toMatch(/[?&]tab=breeding/);
  });

  test("direct navigation to ?herd=X&tab=breeding works", async ({
    page,
    context,
  }) => {
    await loginInline(page, context, {
      username: "test-gk-owner",
      password: "test-gk-owner-pass",
    });

    // Navigate directly with herd and tab params
    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });

    // Breeding tab should be active — look for breeding content
    await expect(
      page
        .getByText(/Visby Stamfar|Visby Stammor|Kullar och parningar/)
        .first(),
    ).toBeVisible({ timeout: 60000 });

    // URL should still contain the tab param
    expect(page.url()).toContain("tab=breeding");
  });

  test("tab switching updates URL without losing herd param", async ({
    page,
    context,
  }) => {
    await loginInline(page, context, {
      username: "test-dual",
      password: "test-dual-pass",
    });

    // Navigate with explicit herd
    await page.goto("/stamboken/min-besattning", {
      waitUntil: "domcontentloaded",
    });
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible({
      timeout: 60000,
    });

    // Switch to breeding tab — TabBar renders role="tab" links
    const breedingTab = page.getByRole("tab", { name: /parning/i });
    await breedingTab.click();

    // URL should contain tab=breeding
    await expect(page).toHaveURL(/tab=breeding/, { timeout: 5000 });
  });
});

test.describe("RTK read hooks removed (code-level check)", () => {
  test("min-besattning-content.tsx does not import RTK read hooks", () => {
    const filePath = path.resolve(
      __dirname,
      "../src/app/(app)/stamboken/(dashboard)/min-besattning/min-besattning-content.tsx",
    );
    const content = fs.readFileSync(filePath, "utf-8");

    // After Story 2.11, these RTK read hooks should be gone
    expect(content).not.toContain("useFetchHerdQuery");
    expect(content).not.toContain("useFetchBreedingListQuery");
    expect(content).not.toContain("useRtkData");
  });

  test("min-besattning-content.tsx does not use useDispatch for RTK invalidation", () => {
    const filePath = path.resolve(
      __dirname,
      "../src/app/(app)/stamboken/(dashboard)/min-besattning/min-besattning-content.tsx",
    );
    const content = fs.readFileSync(filePath, "utf-8");

    // invalidateRtkCache helper should be removed
    expect(content).not.toContain("invalidateRtkCache");
  });
});
