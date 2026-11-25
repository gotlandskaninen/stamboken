import { test, expect, type Page } from "@playwright/test";
import {
  expectTourAxeClean as expectNoAxeViolations,
  startTourFromMenu as startFromMenu,
  tourPopover as tour,
  walkTour as walk,
} from "../e2e-shared/tour";

// The tour (stamboken #229) for an ordinary member (gk-owner storageState).
// Each test starts with empty localStorage, so the offer is always there.

async function openMinBesattning(page: Page) {
  await page.goto("/stamboken/min-besattning");
  // The tabs are server-rendered; the content under them only after hydration.
  await expect(page.locator("#herd-tab-overview")).toBeVisible({
    timeout: 15000,
  });
  await expect(page.getByText("Laddar…")).toBeHidden({ timeout: 20000 });
}

test.describe("Rundtur för en vanlig medlem", () => {
  test("the offer starts the tour, which walks to the end", async ({
    page,
  }) => {
    await openMinBesattning(page);
    const offer = page.getByRole("region", { name: "Rundtur i Stamboken" });
    await offer.getByRole("button", { name: "Visa runt" }).click();

    await expect(page.getByRole("dialog")).toContainText("Min besättning");
    await expect(page.locator(".driver-popover-progress-text")).toHaveText(
      /^1 av \d+$/,
    );
    await expectNoAxeViolations(page);

    const titles = await walk(page);
    expect(titles).toEqual(
      expect.arrayContaining([
        "Min besättning",
        "Kaniner",
        "Kullar och parningar",
        "Årsrapport",
        "Profil",
        "Tyck till",
      ]),
    );
    // An ordinary member has no role step.
    expect(titles).not.toContain("Din roll");
    // The offer's button is gone, so focus goes to the menu.
    await expect(page.getByRole("button", { name: "Account" })).toBeFocused();

    // Answered: the offer does not come back by itself.
    await page.reload();
    await openMinBesattning(page);
    await expect(offer).toHaveCount(0);
  });

  test("Nej tack hides the offer for good, and the menu still starts the tour", async ({
    page,
  }) => {
    await openMinBesattning(page);
    await page.getByRole("button", { name: "Nej tack" }).click();
    await page.reload();
    await openMinBesattning(page);
    await expect(
      page.getByRole("region", { name: "Rundtur i Stamboken" }),
    ).toHaveCount(0);
    await expect(tour(page)).toHaveCount(0);

    // prefers-reduced-motion: no fade.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await startFromMenu(page);
    await expect(page.locator("body")).not.toHaveClass(/driver-fade/);
    await expectNoAxeViolations(page);
  });

  test("Esc ends the tour and gives focus back; it can start again", async ({
    page,
  }) => {
    await openMinBesattning(page);
    await startFromMenu(page);
    const inTour = () =>
      page.evaluate(() => !!document.activeElement?.closest(".driver-popover"));
    await expect.poll(inTour).toBe(true);
    // Tab goes round inside the tour (focus trap).
    for (let i = 0; i < 8; i++) {
      await page.keyboard.press("Tab");
      expect(await inTour()).toBe(true);
    }
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Nästa" })
      .click();
    await page.keyboard.press("Escape");
    await expect(tour(page)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Account" })).toBeFocused();

    // Started again it begins from the first step.
    await startFromMenu(page);
    await expect(page.locator(".driver-popover-progress-text")).toHaveText(
      /^1 av /,
    );
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Stäng rundturen" })
      .click();
    await expect(tour(page)).toHaveCount(0);
  });

  test("on a rabbit's page the tour shows its photo and certificate", async ({
    page,
  }) => {
    await page.goto("/stamboken/individ/G1274-2112");
    await expect(page.locator('[data-tour="rabbit-card"]')).toBeVisible({
      timeout: 15000,
    });
    await startFromMenu(page);
    await expect(page.locator(".driver-popover-title")).toHaveText("Kaninen");
    await expect(
      page.getByRole("dialog").getByRole("link", { name: "Läs mer" }),
    ).toHaveAttribute("href", "/stamboken-online/manual#ladda-upp-ett-foto");
    const titles = await walk(page);
    // Min besättning's tabs are not on this page.
    expect(titles).not.toContain("Kullar och parningar");
  });

  test("starting from the menu answers the offer too", async ({ page }) => {
    await openMinBesattning(page);
    const offer = page.getByRole("region", { name: "Rundtur i Stamboken" });
    await expect(offer).toBeVisible();
    await startFromMenu(page);
    // Gone at once, not only after the tour.
    await expect(offer).toHaveCount(0);
    await page.keyboard.press("Escape");
    await page.reload();
    await openMinBesattning(page);
    await expect(offer).toHaveCount(0);
  });

  test.describe("on a 375 px phone", () => {
    test.use({ viewport: { width: 375, height: 812 }, hasTouch: true });

    test("the menu button stands in for the hidden top links", async ({
      page,
    }) => {
      await openMinBesattning(page);
      await startFromMenu(page);
      await expectNoAxeViolations(page);
      const titles = await walk(page);
      expect(titles).toEqual(
        expect.arrayContaining(["Kaniner", "Årsrapport", "Profil"]),
      );
    });
  });
});
