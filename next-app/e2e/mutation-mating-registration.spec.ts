import { test, expect } from "@playwright/test";

// Mutation tests create real records in the DB.
// CI: fresh DB per run. Local reruns: each run uses a unique date
// (based on timestamp) to avoid duplicate-breeding rejection.

test.describe("Mating Registration", () => {
  test.describe.configure({ mode: "serial" });

  test("registers a new mating via form", async ({ page }) => {
    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });

    // Click "Ny parning" button
    const newMatingBtn = page.getByRole("button", { name: /ny parning/i });
    await expect(newMatingBtn).toBeVisible({ timeout: 60000 });
    await newMatingBtn.click();

    // Select mother via autocomplete — "Visby Saga" (G1274-2115)
    const motherInput = page.getByRole("combobox", { name: /^mor/i });
    await expect(motherInput).toBeVisible({ timeout: 10000 });
    await motherInput.click();
    await motherInput.fill("Visby Saga");
    await page.getByRole("option", { name: /Visby Saga.*G1274-2115/ }).click();

    // Select father via autocomplete — "Visby Storm" (G1274-2116)
    const fatherInput = page.getByRole("combobox", { name: /^far/i });
    await fatherInput.click();
    await fatherInput.fill("Visby Storm");
    await page.getByRole("option", { name: /Visby Storm.*G1274-2116/ }).click();

    // Set a unique mating date to avoid duplicate rejection on rerun.
    // MUI DatePicker fill() is flaky under Next.js 16 hydration timing —
    // click + pressSequentially + Tab commits the value reliably.
    // MUI X v9: pickers render a sectioned field (role=group), not a labeled input
    const dateInput = page.getByRole("group", { name: /parningsdatum/i });
    // The doe may not mate inside the 38-day gestation window of another mating (inclusive), and
    // mutation-manual-flows registers matings for the same pair from 2024-12-01 on. So: the 1st of
    // an odd month Jan-Sep 2024 (slots >= 59 days apart, the last window ends 2024-11-08), chosen per
    // minute and moved one slot on each retry, so a retry after an insert that went through still
    // gets a free date. Five runs in a row fit one seed; then a fresh stack (as in the manual spec).
    const slot = (Math.floor(Date.now() / 60000) + test.info().retry) % 5;
    const matingDate = `2024${String(slot * 2 + 1).padStart(2, "0")}01`;
    await dateInput.locator('[data-sectionindex="0"]').click();
    await dateInput.pressSequentially(matingDate);
    await dateInput.press("Tab");

    // Submit form
    const submitBtn = page.getByRole("button", { name: /registrera parning/i });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    // Verify success snackbar
    await expect(page.getByText(/parning registrerad/i)).toBeVisible({
      timeout: 15000,
    });
  });

  test("submit is disabled without parents", async ({ page }) => {
    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });

    const newMatingBtn = page.getByRole("button", { name: /ny parning/i });
    await expect(newMatingBtn).toBeVisible({ timeout: 60000 });
    await newMatingBtn.click();

    // Submit button should be disabled since mother/father not selected
    const submitBtn = page.getByRole("button", { name: /registrera parning/i });
    await expect(submitBtn).toBeDisabled();

    // Swedish labels should be visible on form fields
    await expect(page.getByRole("combobox", { name: /^mor/i })).toBeVisible();
    await expect(page.getByRole("combobox", { name: /^far/i })).toBeVisible();
    await expect(
      page.getByRole("group", { name: /parningsdatum/i }),
    ).toBeVisible();
  });
});
