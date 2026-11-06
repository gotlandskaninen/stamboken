import { test, expect } from "@playwright/test";

// Mutation tests create real records in the DB.
// CI: fresh DB per run. Local reruns: each run uses a unique date
// (based on timestamp) to avoid duplicate-breeding rejection.

test.describe("Litter Registration", () => {
  test.describe.configure({ mode: "serial" });

  test("registers a new litter via form", async ({ page }) => {
    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });

    // Click "Ny kull" button
    const newLitterBtn = page.getByRole("button", { name: /ny kull/i });
    await expect(newLitterBtn).toBeVisible({ timeout: 60000 });
    await newLitterBtn.click();

    // Select mother via autocomplete — "Visby Dimma" (G1274-2117)
    const motherInput = page.getByRole("combobox", { name: /^mor/i });
    await expect(motherInput).toBeVisible({ timeout: 10000 });
    await motherInput.click();
    await motherInput.fill("Visby Dimma");
    await page.getByRole("option", { name: /Visby Dimma.*G1274-2117/ }).click();

    // Select father via autocomplete — "Visby Blixt" (G1274-2118)
    const fatherInput = page.getByRole("combobox", { name: /^far/i });
    await fatherInput.click();
    await fatherInput.fill("Visby Blixt");
    await page.getByRole("option", { name: /Visby Blixt.*G1274-2118/ }).click();

    // Set a unique birth date to avoid duplicate rejection on rerun.
    // MUI DatePicker input is a masked field — fill() alone doesn't
    // reliably fire the onChange that updates formData.birthDate under
    // Next.js 16's hydration timing. Click to focus, type character by
    // character, then blur via Tab to commit the value.
    // MUI X v9: pickers render a sectioned field (role=group), not a labeled input
    const dateInput = page.getByRole("group", { name: /födelsedatum/i });
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

    // Fill "Antal födda"
    await page.getByLabel(/antal födda/i).fill("5");

    // Submit form
    const submitBtn = page.getByRole("button", { name: /registrera kull/i });
    await expect(submitBtn).toBeEnabled();
    await submitBtn.click();

    // Verify success snackbar
    await expect(page.getByText(/kull registrerad/i)).toBeVisible({
      timeout: 15000,
    });
  });

  test("submit is disabled without required fields", async ({ page }) => {
    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });

    const newLitterBtn = page.getByRole("button", { name: /ny kull/i });
    await expect(newLitterBtn).toBeVisible({ timeout: 60000 });
    await newLitterBtn.click();

    // Submit button should be disabled since mother/father and antal not filled
    const submitBtn = page.getByRole("button", { name: /registrera kull/i });
    await expect(submitBtn).toBeDisabled();

    // Swedish labels should be visible on form fields
    await expect(page.getByRole("combobox", { name: /^mor/i })).toBeVisible();
    await expect(page.getByRole("combobox", { name: /^far/i })).toBeVisible();
    await expect(
      page.getByRole("group", { name: /födelsedatum/i }),
    ).toBeVisible();
    await expect(page.getByLabel(/antal födda/i)).toBeVisible();
  });

  test("mobile: form is usable at 375px", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });

    await page.goto("/stamboken/min-besattning?tab=breeding", {
      waitUntil: "domcontentloaded",
    });

    const newLitterBtn = page.getByRole("button", { name: /ny kull/i });
    await expect(newLitterBtn).toBeVisible({ timeout: 60000 });
    await newLitterBtn.click();

    // Form should be visible without horizontal scroll
    const motherInput = page.getByRole("combobox", { name: /^mor/i });
    await expect(motherInput).toBeVisible();

    // Check no horizontal scrollbar
    const scrollWidth = await page.evaluate(
      () => document.documentElement.scrollWidth,
    );
    const clientWidth = await page.evaluate(
      () => document.documentElement.clientWidth,
    );
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1); // +1 for rounding

    // Check submit button has 48px+ height (touch target requirement)
    const submitBtn = page.getByRole("button", { name: /registrera kull/i });
    const submitBox = await submitBtn.boundingBox();
    expect(submitBox).not.toBeNull();
    expect(submitBox!.height).toBeGreaterThanOrEqual(48);

    // Check cancel button also has 48px+ height
    const cancelBtn = page.getByRole("button", { name: /avbryt/i });
    const cancelBox = await cancelBtn.boundingBox();
    expect(cancelBox).not.toBeNull();
    expect(cancelBox!.height).toBeGreaterThanOrEqual(48);
  });
});
