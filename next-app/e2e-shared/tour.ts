import { expect, type Locator, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

// Helpers for the tour (stamboken #229), which driver.js draws.

export const tourPopover = (page: Page) => page.locator(".driver-popover");

export async function startTourFromMenu(page: Page) {
  // A click before React has hydrated the menu button is lost.
  await page.waitForFunction(
    () =>
      Object.keys(document.querySelector('[data-tour="user-menu"]') ?? {}).some(
        (k) => k.startsWith("__reactFiber"),
      ),
    undefined,
    { timeout: 60_000 },
  );
  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("menuitem", { name: "Visa runt" }).click();
  await expect(tourPopover(page)).toBeVisible();
}

/**
 * Walks the tour with Nästa to Klar and returns every step's title. Waits for
 * the progress text per step, so a title is never read from the step before.
 */
export async function walkTour(
  page: Page,
  onStep?: (title: string, dialog: Locator) => Promise<void>,
): Promise<string[]> {
  const dialog = page.getByRole("dialog");
  const progress = page.locator(".driver-popover-progress-text");
  await expect(progress).toHaveText(/^1 av \d+$/);
  const total = Number((await progress.innerText()).split(" av ")[1]);
  const titles: string[] = [];
  for (let i = 1; i <= total; i++) {
    await expect(progress).toHaveText(`${i} av ${total}`);
    // Focus stays in the tour (focus trap).
    await expect
      .poll(() =>
        page.evaluate(
          () => !!document.activeElement?.closest(".driver-popover"),
        ),
      )
      .toBe(true);
    const title = (
      await page.locator(".driver-popover-title").innerText()
    ).trim();
    titles.push(title);
    await onStep?.(title, dialog);
    await dialog
      .getByRole("button", { name: i === total ? "Klar" : "Nästa" })
      .click();
  }
  await expect(tourPopover(page)).toHaveCount(0);
  return titles;
}

/** axe on the tour's own popover: a hard check, unlike a11y-axe.spec.ts. */
export async function expectTourAxeClean(page: Page) {
  // Contrast is only right once the fade-in has ended.
  await tourPopover(page).evaluate((el) =>
    Promise.all(
      el.ownerDocument
        .getAnimations()
        .map((a) => a.finished.catch(() => undefined)),
    ),
  );
  const { violations } = await new AxeBuilder({ page })
    .include(".driver-popover")
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
}
