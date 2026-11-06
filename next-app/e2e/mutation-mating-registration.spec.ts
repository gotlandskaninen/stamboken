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
    // Derived from whole seconds, not a bit shift: `Date.now() >> n` casts to
    // int32, which is negative for weeks at a time and made the month "00".
    const seconds = Math.floor(Date.now() / 1000);
    const uniqueDay = String((seconds % 28) + 1).padStart(2, "0");
    const uniqueMonth = String((Math.floor(seconds / 28) % 12) + 1).padStart(
      2,
      "0",
    );
    await dateInput.locator('[data-sectionindex="0"]').click();
    await dateInput.pressSequentially(`2025${uniqueMonth}${uniqueDay}`);
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
