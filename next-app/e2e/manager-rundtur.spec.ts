import { test, expect } from "@playwright/test";
import {
  expectTourAxeClean,
  startTourFromMenu,
  walkTour,
} from "../e2e-shared/tour";

// The tour (stamboken #229) for a genbanksansvarig (gk-manager storageState):
// the role step, and the page step on the matrikel, which managers keep too.

test("the tour adds the role and matrikel steps for a genbanksansvarig", async ({
  page,
}) => {
  await page.goto("/medlem/matrikel");
  await expect(page.locator('[data-tour="matrikel"]')).toBeVisible({
    timeout: 15000,
  });
  // The offer belongs to Min besättning only.
  await expect(
    page.getByRole("region", { name: "Rundtur i Stamboken" }),
  ).toHaveCount(0);

  await startTourFromMenu(page);
  await expect(page.getByRole("dialog")).toContainText("Matrikeln");
  await expectTourAxeClean(page);

  const titles = await walkTour(page, async (title, dialog) => {
    if (title === "Din roll")
      await expect(dialog).toContainText("Adminpanelen och Matrikel");
  });
  expect(titles).toEqual(
    expect.arrayContaining(["Matrikeln", "Din roll", "Tyck till"]),
  );
  // Min besättning's tabs are not on this page.
  expect(titles).not.toContain("Kullar och parningar");
});
