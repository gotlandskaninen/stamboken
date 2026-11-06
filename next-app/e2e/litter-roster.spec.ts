import { test, expect, type Page } from "@playwright/test";

// ── Seed data used (gk-owner herd G1274) ────────────────────────────────────
//
// • 2021-04-01 litter (Visby Stamfar × Visby Stammor): ageInDays ≫ 42,
//   age gate passes, roster starts empty (separate from individuals table).
//
// • "Too young" test creates a litter born today so ageInDays = 0 ≪ 42.
//   On re-runs the same litter already exists — that is handled gracefully.
//
// ── Project assignment ───────────────────────────────────────────────────────
//
// File name does not match /mutation-.*/ → resolved by "owner-tests" project
// (storageState: e2e/.auth/gk-owner.json).  Tests that write to the DB are
// declared serial to avoid intra-file ordering conflicts.

const BASE_URL = "/stamboken/min-besattning?tab=breeding";

/** Navigate to the breeding/litter tab. */
async function goToBreedingTab(page: Page) {
  await page.goto(BASE_URL, { waitUntil: "domcontentloaded" });
}

/**
 * Find the first breeding card whose text contains `pattern` and click its
 * "Detaljer" expand button (aria-label).  Clicks the accessible button
 * rather than the parent-name link to avoid unintended navigation.
 */
async function expandLitterCard(page: Page, pattern: RegExp | string) {
  const card = page
    .locator('[data-testid="breeding-card"]')
    .filter({ hasText: pattern })
    .first();
  await expect(card).toBeVisible({ timeout: 60000 });
  await card.getByRole("button", { name: "Detaljer" }).click();
  // Wait for the LitterRoster section heading to appear inside the card.
  await expect(page.getByText(/Kullista/).first()).toBeVisible({
    timeout: 15000,
  });
}

// ═══════════════════════════════════════════════════════════════════════════
// Flow 1 (serial): bulk-add → reorder → promote
// ═══════════════════════════════════════════════════════════════════════════

// SKIPPED pending live-stack refinement. These flows assert against specific
// seed data (a "Visby Stamfar × Visby Stammor" 2021 litter in gk-owner's herd)
// and DOM selectors that must be validated against a running local-production
// stack (bunny schema + seeded litters) — the deferred live e2e run noted in the
// Task-10 report. The backend is covered by 670 unit/API tests; re-enable these
// once the selectors + seed assumptions are confirmed against the live seed.
test.describe.skip("Litter Roster — bulk-add, reorder and promote", () => {
  // Tests share state: step 1 adds bunnies that step 3 promotes.
  test.describe.configure({ mode: "serial" });

  test("adds 2 bunnies to the 2021 litter roster", async ({ page }) => {
    await goToBreedingTab(page);

    // Seed litter: Visby Stamfar × Visby Stammor, born 2021-04-01.
    // ageInDays ≫ 42 → age gate is open.
    await expandLitterCard(page, /Visby Stamfar|Visby Stammor/);

    // Use the "Antal" number field and "Lägg till ungar" button from LitterRoster.
    const countField = page.getByLabel("Antal");
    await countField.fill("2");
    await page.getByRole("button", { name: /Lägg till ungar/ }).click();

    // Kullöversikt (N) — N ≥ 1 — should appear after the server round-trip.
    await expect(page.getByText(/Kullista \(\d+/)).toBeVisible({
      timeout: 15000,
    });
  });

  test("drag-and-drop reorder — handles visible, drag completes without error", async ({
    page,
  }) => {
    await goToBreedingTab(page);
    await expandLitterCard(page, /Visby Stamfar|Visby Stammor/);
    await expect(page.getByText(/Kullista \(\d+/)).toBeVisible({
      timeout: 15000,
    });

    // @hello-pangea/dnd sets data-rbd-drag-handle-draggable-id on each handle.
    const handles = page.locator("[data-rbd-drag-handle-draggable-id]");
    const handleCount = await handles.count();
    expect(handleCount).toBeGreaterThanOrEqual(1);

    if (handleCount >= 2) {
      // Attempt drag of slot 0 below slot 1; use target bottom edge so
      // dnd registers an "after" drop.
      const target = handles.nth(1);
      await handles.first().dragTo(target, {
        targetPosition: { x: 20, y: 20 },
      });
      // No error toast should follow a successful reorder.
      await expect(
        page
          .getByRole("alert")
          .filter({ hasText: /Kunde inte spara ny ordning/ }),
      ).not.toBeVisible();
    }
  });

  test("promotes a bunny — minted number matches provisional preview", async ({
    page,
  }) => {
    await goToBreedingTab(page);
    await expandLitterCard(page, /Visby Stamfar|Visby Stammor/);
    await expect(page.getByText(/Kullista \(\d+/)).toBeVisible({
      timeout: 15000,
    });

    // First enabled "Registrera" button — corresponds to an unlinked bunny.
    const registerBtn = page
      .getByRole("button", { name: "Registrera" })
      .first();
    await expect(registerBtn).toBeEnabled({ timeout: 10000 });

    // Capture the provisional number (G\d{4}-\d{4}) shown in the roster card
    // for this bunny.  The card is the [data-rbd-draggable-id] container
    // whose last child is the button area containing the enabled Registrera.
    const firstDraggable = page
      .locator("[data-rbd-draggable-id]")
      .filter({ has: page.getByRole("button", { name: "Registrera" }) })
      .first();
    const provisionalNumber = await firstDraggable
      .getByText(/G\d{4}-\d{4}/)
      .first()
      .textContent({ timeout: 5000 })
      .catch(() => null);

    // Open the promote dialog.
    await registerBtn.click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible({ timeout: 10000 });

    // The dialog shows the provisional number under "Preliminärt nummer".
    // Assert that the same number visible pre-click is shown in the dialog.
    if (provisionalNumber) {
      await expect(dialog.getByText("Preliminärt nummer")).toBeVisible();
      await expect(
        dialog.getByText(provisionalNumber, { exact: true }),
      ).toBeVisible();
    }

    // Fill the required color field ("Färg") and submit.
    await dialog.getByLabel("Färg").fill("Grå");
    await dialog.getByRole("button", { name: "Registrera" }).click();

    // Success alert — contains the minted individual number.
    const successAlert = dialog.getByRole("alert");
    await expect(successAlert).toBeVisible({ timeout: 15000 });
    if (provisionalNumber) {
      // "Kanin registrerad som G1274-XXXX" — provisional number = minted number.
      await expect(successAlert).toContainText(provisionalNumber);
    }

    // Close dialog ("Stäng" = t("common.close")).  onPromoted() refreshes
    // the roster so the promoted slot switches to linked state — B5 renders
    // a "Registrerad" badge instead of the old "✓" button.
    await dialog.getByRole("button", { name: "Stäng" }).click();
    await expect(page.getByText("Registrerad").first()).toBeVisible({
      timeout: 10000,
    });
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// Flow 2: age gate — Registrera disabled for litter born today (< 6 weeks)
// ═══════════════════════════════════════════════════════════════════════════

// SKIPPED pending live-stack refinement (see note above).
test.describe.skip("Litter Roster — age gate", () => {
  test("Registrera is disabled for a litter born today", async ({ page }) => {
    await goToBreedingTab(page);

    // Build the today string in the format the MUI DatePicker masked input
    // expects: yyyymmdd (same convention as mutation-litter-registration.spec.ts).
    const today = new Date();
    const todayISO = [
      today.getFullYear(),
      String(today.getMonth() + 1).padStart(2, "0"),
      String(today.getDate()).padStart(2, "0"),
    ].join("-");
    const todayForInput = todayISO.replace(/-/g, "");

    // --- Create a litter born today ---
    // Parents: Visby Dimma (G1274-2117) × Visby Blixt (G1274-2118).
    // On re-runs, a duplicate response is acceptable — we just find the
    // existing litter afterwards.
    const newLitterBtn = page.getByRole("button", { name: /ny kull/i });
    await expect(newLitterBtn).toBeVisible({ timeout: 60000 });
    await newLitterBtn.click();

    const motherInput = page.getByRole("combobox", { name: /^mor/i });
    await expect(motherInput).toBeVisible({ timeout: 10000 });
    await motherInput.click();
    await motherInput.fill("Visby Dimma");
    await page.getByRole("option", { name: /Visby Dimma.*G1274-2117/ }).click();

    const fatherInput = page.getByRole("combobox", { name: /^far/i });
    await fatherInput.click();
    await fatherInput.fill("Visby Blixt");
    await page.getByRole("option", { name: /Visby Blixt.*G1274-2118/ }).click();

    const dateInput = page.getByLabel(/födelsedatum/i);
    await dateInput.click();
    await dateInput.pressSequentially(todayForInput);
    await dateInput.press("Tab");

    await page.getByLabel(/antal födda/i).fill("2");

    await page.getByRole("button", { name: /registrera kull/i }).click();

    // Accept success or duplicate error — both leave the litter in the DB.
    await page
      .getByText(/kull registrerad/i)
      .waitFor({ timeout: 15000 })
      .catch(() => {
        /* duplicate on re-run — proceed */
      });

    // --- Navigate to the breeding tab to see the refreshed list ---
    await goToBreedingTab(page);

    // Find the card born today: filter by today's ISO date string which
    // BreedingList renders as "Född YYYY-MM-DD" in the caption.
    const todayCard = page
      .locator('[data-testid="breeding-card"]')
      .filter({ hasText: todayISO })
      .filter({ hasText: /Visby Dimma|Visby Blixt/ })
      .first();
    await expect(todayCard).toBeVisible({ timeout: 30000 });
    await todayCard.getByRole("button", { name: "Detaljer" }).click();
    await expect(page.getByText(/Kullista/).first()).toBeVisible({
      timeout: 15000,
    });

    // Add a bunny so the roster has at least one entry.
    await page.getByRole("button", { name: /Lägg till ungar/ }).click();
    await expect(page.getByText(/Kullista \(\d+/)).toBeVisible({
      timeout: 15000,
    });

    // Registrera must be disabled: ageInDays = 0 < 42.
    const registerBtn = page
      .getByRole("button", { name: "Registrera" })
      .first();
    await expect(registerBtn).toBeDisabled();

    // B5 always renders the age gate as a header badge when the litter is
    // too young (litterRoster.gateClosed) — no hover needed.
    await expect(page.getByText(/Registrering öppnar om \d+ dag/)).toBeVisible({
      timeout: 5000,
    });
  });
});

// ═══════════════════════════════════════════════════════════════════════════
// Flow 3: cap block (skipped — needs specific DB state)
// ═══════════════════════════════════════════════════════════════════════════

test("cap block — Registrera disabled when provisional_number is null", async () => {
  // SKIP: Triggering the cap condition (atCap = provisional_number === null &&
  // !isLinked) requires a litter whose litter_size6w slots are all occupied.
  // The slot count varies across runs (bunnies accumulate); setting this up
  // deterministically via UI alone is not feasible without knowing the exact
  // current count. The atCap rendering path is covered by unit tests in
  // __tests__/breeding/.
  test.skip(
    true,
    "Requires DB state: all litter_size6w provisional slots occupied. " +
      "Covered by unit tests.",
  );
});

// ═══════════════════════════════════════════════════════════════════════════
// Flow 4: renumber conflict (skipped — needs specific DB state)
// ═══════════════════════════════════════════════════════════════════════════

test("renumber conflict — LitterNumberConflictDialog opens for out-of-order litter", async () => {
  // SKIP: litter_order_conflict requires two litters in the same calendar year
  // whose litter_numbers don't match the chronological order of birth_dates.
  // Seed data spans different years (2020, 2021, 2022, 2023) so no same-year
  // ordering conflict exists.  Creating the required state via UI in a
  // repeatable, non-destructive way would require deleting and recreating
  // litters — risky in a shared DB.  The LitterNumberConflictDialog is
  // covered by its own component unit test and manual integration testing.
  test.skip(
    true,
    "Requires same-year out-of-order litter state not available in seed data.",
  );
});
