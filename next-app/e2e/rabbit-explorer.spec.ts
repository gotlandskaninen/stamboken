import { test, expect } from "@playwright/test";

// Auth is handled by storageState (gk-owner) set in playwright.config.ts.
// No mock setup needed — tests run against the real API + seed data.

test.describe("Rabbit Explorer — /alla-kaniner", () => {
  test("page loads with seed data", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");
    const grid = page.locator(".MuiDataGrid-root");
    await expect(grid).toBeVisible({ timeout: 15000 });
    const rows = page.locator(".MuiDataGrid-row");
    await expect(rows.first()).toBeVisible({ timeout: 10000 });
  });

  test("column headers are visible", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 15000,
    });

    const visibleHeaders = [
      "Individnummer",
      "Namn",
      "Kön",
      "Födelsedatum",
      "Status",
      "Besättning",
      "Kullstorlek",
      "Mor",
      "Far",
    ];
    for (const header of visibleHeaders) {
      await expect(
        page.locator(`.MuiDataGrid-columnHeader:has-text("${header}")`),
      ).toBeVisible();
    }

    // Färg column may require horizontal scroll
    const scroller = page.locator(".MuiDataGrid-virtualScroller");
    await scroller.evaluate((el) => (el.scrollLeft = el.scrollWidth));
    await expect(
      page.locator('.MuiDataGrid-columnHeader:has-text("Färg")'),
    ).toBeVisible({ timeout: 5000 });
  });

  test("pagination works at pageSize 25", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 15000,
    });

    // Switch to 25 rows per page — use combobox role to avoid strict mode violation
    const pageSizeSelect = page.getByRole("combobox", {
      name: /rader per sida/i,
    });
    await pageSizeSelect.click();
    await page.getByRole("option", { name: "25" }).click();

    // Pagination display uses em-dash (–) and Swedish locale
    const paginationDisplay = page.locator(".MuiTablePagination-displayedRows");
    await expect(paginationDisplay).toContainText(/1–25/);

    // Go to page 2 — seed has >25 GK individuals so next page exists
    const nextButton = page.getByRole("button", { name: /nästa sida/i });
    await expect(nextButton).toBeEnabled();
    await nextButton.click();

    // Page 2 should show a different range (not 1–25)
    await expect(paginationDisplay).not.toContainText(/1–25/);
  });

  test("search filters by name", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 15000,
    });

    // Search for a known seed individual
    const searchField = page.getByPlaceholder(/Sök/);
    await searchField.fill("Visby Viking");

    // Wait for debounce + filtered response — check the row text content
    await expect(page.locator(".MuiDataGrid-row").first()).toContainText(
      "Visby Viking",
      { timeout: 10000 },
    );
  });

  test("sort by column header changes order", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 15000,
    });

    const firstNameCell = page
      .locator('.MuiDataGrid-cell[data-field="name"]')
      .first();
    const nameBefore = await firstNameCell.textContent();

    // Default sort is name asc. One click toggles to desc.
    await page.locator('.MuiDataGrid-columnHeader:has-text("Namn")').click();

    // Wait for re-sorted data to load
    await page.waitForTimeout(500);
    const nameAfterSort = await firstNameCell.textContent();
    expect(nameAfterSort).not.toBe(nameBefore);
  });

  test("status filter shows only active individuals", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 15000,
    });

    // Open the Status select
    await page
      .locator(".MuiFormControl-root", { hasText: "Status" })
      .locator(".MuiSelect-select")
      .click();
    // Wait for the filtered response: the old unfiltered rows stay visible
    // (RTK Query keeps previous data) until it arrives.
    await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes("/api/individuals") &&
          r.url().includes("status=active"),
      ),
      page.getByRole("option", { name: "Aktiv", exact: true }).click(),
    ]);

    // After filtering, wait for rows to reload then verify status text
    await page.locator(".MuiDataGrid-row").first().waitFor({ timeout: 10000 });
    // Check first few rows have "Aktiv" status text
    const statusCells = page.locator('.MuiDataGrid-cell[data-field="status"]');
    const count = await statusCells.count();
    for (let i = 0; i < Math.min(count, 3); i++) {
      await expect(statusCells.nth(i)).toContainText(/aktiv/i);
    }
  });

  test("sex filter shows only female individuals", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 15000,
    });

    // Open the Kön select
    await page
      .locator(".MuiFormControl-root", { hasText: "Kön" })
      .locator(".MuiSelect-select")
      .click();
    // Wait for the filtered response: the old unfiltered rows stay visible
    // (RTK Query keeps previous data) until it arrives.
    await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes("/api/individuals") &&
          r.url().includes("sex=female"),
      ),
      page.getByRole("option", { name: "Hona" }).click(),
    ]);

    // After filtering, visible sex cells should show "Hona", never "Hane"
    await page.locator(".MuiDataGrid-row").first().waitFor({ timeout: 5000 });
    const sexCells = page.locator('.MuiDataGrid-cell[data-field="sex"]');
    const count = await sexCells.count();
    for (let i = 0; i < Math.min(count, 5); i++) {
      await expect(sexCells.nth(i)).toContainText("Hona");
    }
  });

  test("column visibility toggle opens panel with checkboxes", async ({
    page,
  }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 15000,
    });

    // Open column selector toolbar button (localeText: toolbarColumnsLabel = "Välj kolumner")
    await page.getByRole("button", { name: "Välj kolumner" }).click();

    // Panel should list columns
    await expect(
      page.getByRole("checkbox", { name: "Individnummer" }),
    ).toBeVisible();
    await expect(
      page.getByRole("checkbox", { name: "Kullstorlek 6v" }),
    ).toBeVisible();
    await expect(page.getByText("Visa/dölj alla")).toBeVisible();
  });

  test("row click navigates to individual page", async ({ page }) => {
    test.setTimeout(60000);
    await page.goto("/stamboken/alla-kaniner");
    const firstRow = page.locator(".MuiDataGrid-row").first();
    await expect(firstRow).toBeVisible({ timeout: 15000 });

    const numberCell = firstRow.locator(
      '.MuiDataGrid-cell[data-field="number"]',
    );
    const number = await numberCell.textContent();

    await firstRow.click();
    await page.waitForURL(/\/stamboken\/individ\//, {
      timeout: 30000,
      waitUntil: "commit",
    });
    expect(page.url()).toContain(`/individ/${number}`);
  });

  test("empty search shows no-rows message", async ({ page }) => {
    await page.goto("/stamboken/alla-kaniner");
    await expect(page.locator(".MuiDataGrid-row").first()).toBeVisible({
      timeout: 15000,
    });

    // Search for a string that matches nothing in seed data
    const searchField = page.getByPlaceholder(/Sök/);
    await searchField.fill("XYZNOTEXISTENTRABBIT99999");

    await expect(
      page.getByRole("grid").getByText("Inga kaniner hittades"),
    ).toBeVisible({
      timeout: 5000,
    });
  });
});
