import { test, expect } from "@playwright/test";

// Story 3.3 — below 900px the explorer is a tappable list, not the DataGrid.
// Auth via storageState (gk-owner); runs against the real API + seed data.

test.use({ viewport: { width: 375, height: 812 } });

const list = '[data-testid="explorer-mobile-list"]';
const rows = `${list} a[href^="/stamboken/individ/"]`;

test.describe("Rabbit Explorer — mobile (375px)", () => {
  test("shows the list instead of the DataGrid, no horizontal scroll", async ({
    page,
  }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(rows).first()).toBeVisible({ timeout: 15000 });
    await expect(page.locator(".MuiDataGrid-root")).toBeHidden();

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("search filters the list", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(rows).first()).toBeVisible({ timeout: 15000 });

    await page.getByPlaceholder(/Sök/).fill("Visby Viking");
    await expect(page.locator(rows).first()).toContainText("Visby Viking", {
      timeout: 10000,
    });
  });

  test("Visa fler appends the next page", async ({ page }) => {
    test.setTimeout(90000);
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(rows).first()).toBeVisible({ timeout: 15000 });
    const hrefs = () =>
      page
        .locator(rows)
        .evaluateAll((els) => els.map((el) => el.getAttribute("href")));
    const firstPage = await hrefs();

    // A tap during hydration can be lost (React replays it, then the dev
    // StrictMode re-run of the search effect resets the page), so repeat the
    // tap until it actually requests page 2. The prefix check below still
    // catches a page that replaces instead of appends.
    await expect(async () => {
      await Promise.all([
        page.waitForRequest(/\/api\/individuals\?page=2&/, { timeout: 3000 }),
        page
          .getByRole("button", { name: "Visa fler" })
          .click({ timeout: 3000 }),
      ]);
    }).toPass({ timeout: 45000 });
    await expect
      .poll(async () => (await hrefs()).length, { timeout: 10000 })
      .toBeGreaterThan(firstPage.length);

    // Page 2 is appended below page 1, not swapped in, and nothing repeats.
    const all = await hrefs();
    expect(all.slice(0, firstPage.length)).toEqual(firstPage);
    expect(new Set(all).size).toBe(all.length);
  });

  test("tap navigates to the individual page", async ({ page }) => {
    test.setTimeout(60000);
    await page.goto("/stamboken/alla-kaniner");
    const first = page.locator(rows).first();
    await expect(first).toBeVisible({ timeout: 15000 });
    const href = await first.getAttribute("href");

    await first.click();
    await page.waitForURL(/\/stamboken\/individ\//, {
      timeout: 30000,
      waitUntil: "commit",
    });
    expect(page.url()).toContain(href!);
  });
});
