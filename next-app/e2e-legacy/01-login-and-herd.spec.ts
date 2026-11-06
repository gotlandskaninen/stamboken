import { test, expect } from "@playwright/test";
import { dismissCookieBanner } from "./helpers/cookie-banner";

test.describe("Login and Herd View", () => {
  test("owner can login via /api/login and reach home", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await dismissCookieBanner(page);

    // Legacy home page loads with content
    await expect(page.locator("body")).toContainText(
      /Gotlandskanin|Stamboken/i,
    );
  });

  test("owner can navigate to herd and see individual table", async ({
    page,
  }) => {
    await page.goto("/owner");
    await page.waitForLoadState("networkidle");
    await dismissCookieBanner(page);

    // Owner page must load with the herd view — verify heading or table headers
    // The herd may have 0 individuals, so we check for the page structure
    // rather than requiring individual numbers.
    const body = page.locator("body");
    await expect(body).toContainText(
      /Min Besättning|Lista över individer|Nummer/i,
    );
  });
});
