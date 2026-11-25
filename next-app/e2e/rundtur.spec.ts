import { test, expect, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// The tour (stamboken #229) for an ordinary member (gk-owner storageState).
// Each test starts with empty localStorage, so the offer is always there.

const tour = (page: Page) => page.locator(".driver-popover");

async function openMinBesattning(page: Page) {
  await page.goto("/stamboken/min-besattning");
  await expect(page.locator("#herd-tab-overview")).toBeVisible({
    timeout: 15000,
  });
}

async function startFromMenu(page: Page) {
  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("menuitem", { name: "Visa runt" }).click();
  await expect(tour(page)).toBeVisible();
}

/** Clicks Nästa to the end and returns every step's title. */
async function walk(page: Page): Promise<string[]> {
  const titles: string[] = [];
  for (let i = 0; i < 30; i++) {
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    // Focus stays in the tour (focus trap).
    await expect
      .poll(() =>
        page.evaluate(
          () => !!document.activeElement?.closest(".driver-popover"),
        ),
      )
      .toBe(true);
    titles.push(
      (await page.locator(".driver-popover-title").innerText()).trim(),
    );
    const done = dialog.getByRole("button", { name: "Klar" });
    if (await done.isVisible()) {
      await done.click();
      return titles;
    }
    await dialog.getByRole("button", { name: "Nästa" }).click();
  }
  throw new Error("the tour did not end");
}

async function expectNoAxeViolations(page: Page) {
  const { violations } = await new AxeBuilder({ page })
    .include(".driver-popover")
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
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
    await expect(tour(page)).toHaveCount(0);

    // Answered: the offer does not come back by itself.
    await page.reload();
    await expect(page.locator("#herd-tab-overview")).toBeVisible();
    await expect(offer).toHaveCount(0);
  });

  test("Nej tack hides the offer for good, and the menu still starts the tour", async ({
    page,
  }) => {
    await openMinBesattning(page);
    await page.getByRole("button", { name: "Nej tack" }).click();
    await page.reload();
    await expect(page.locator("#herd-tab-overview")).toBeVisible();
    await expect(
      page.getByRole("region", { name: "Rundtur i Stamboken" }),
    ).toHaveCount(0);
    await expect(tour(page)).toHaveCount(0);

    await startFromMenu(page);
    await expectNoAxeViolations(page);
  });

  test("Esc ends the tour and gives focus back; it can start again", async ({
    page,
  }) => {
    await openMinBesattning(page);
    await startFromMenu(page);
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
