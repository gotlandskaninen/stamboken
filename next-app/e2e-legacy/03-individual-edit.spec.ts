import { test, expect } from "@playwright/test";
import { dismissCookieBanner } from "./helpers/cookie-banner";

test.describe("Individual Edit", () => {
  test("edit individual notes, save, and verify persistence", async ({
    page,
  }) => {
    await page.goto("/owner");
    await page.waitForLoadState("networkidle");
    await dismissCookieBanner(page);

    // The legacy UI uses a table — click the edit icon to open detail
    const table = page.locator("table[aria-label='enhanced table']");
    const rows = table.locator("tbody tr");

    // A pass on an empty herd proves nothing (Phase 20 Task 6, brief step 2).
    await expect(rows.first()).toBeVisible({ timeout: 15000 });
    expect(await rows.count()).toBeGreaterThan(0);

    // Both backends answer "Invalid parents" when saving an individual with no
    // recorded mother or father (data_access.update_individual looks up
    // form[parent]["number"]), so pick a row that shows both parents.
    const number = /[GM]\d+-\d+/g;
    const rowTexts = await rows.allInnerTexts();
    const index = rowTexts.findIndex(
      (text) => (text.match(number) ?? []).length >= 3,
    );
    expect(index, "a row with both parents").toBeGreaterThanOrEqual(0);
    const individual = (rowTexts[index].match(number) ?? [])[0];

    // Click edit icon (first cell) to open individual detail
    const editCell = rows.nth(index).locator("td").first();
    await editCell.click();
    await page.waitForLoadState("networkidle");

    // Legacy individual view opens inline with an editable notes field. The
    // point of this spec is the round trip, so the field has to be there.
    // Against a full-size herd the detail view needs noticeably longer to
    // render than against the local-production fixture.
    const notesField = page.locator("textarea").first();
    await expect(notesField).toBeVisible({ timeout: 30000 });

    const timestamp = `Regression test ${Date.now()}`;
    await notesField.fill(timestamp);

    // Click save button ("Spara")
    const saveButton = page.locator("button").filter({ hasText: /Spara/i });
    await expect(saveButton).toBeVisible({ timeout: 5000 });
    await saveButton.click();
    await page.waitForLoadState("networkidle");

    // Reload the page and verify persistence
    await page.reload();
    await page.waitForLoadState("networkidle");

    // Re-open the same individual
    await dismissCookieBanner(page);
    const rowsAfter = page.locator(
      "table[aria-label='enhanced table'] tbody tr",
    );
    const sameRow = rowsAfter.filter({ hasText: individual });
    await expect(sameRow.first()).toBeVisible({ timeout: 15000 });
    await sameRow.first().locator("td").first().click();
    await page.waitForLoadState("networkidle");
    // The persisted effect, not just a successful-looking request.
    await expect(page.locator("body")).toContainText(timestamp);
  });
});
