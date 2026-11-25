import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";

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

  await page.getByRole("button", { name: "Account" }).click();
  await page.getByRole("menuitem", { name: "Visa runt" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("Matrikeln");
  const { violations } = await new AxeBuilder({ page })
    .include(".driver-popover")
    .analyze();
  expect(violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);

  const titles: string[] = [];
  for (let i = 0; i < 30; i++) {
    titles.push(
      (await page.locator(".driver-popover-title").innerText()).trim(),
    );
    if (titles.at(-1) === "Din roll")
      await expect(dialog).toContainText("Adminpanelen och Matrikel");
    const done = dialog.getByRole("button", { name: "Klar" });
    if (await done.isVisible()) {
      await done.click();
      break;
    }
    await dialog.getByRole("button", { name: "Nästa" }).click();
  }
  expect(titles).toEqual(
    expect.arrayContaining(["Matrikeln", "Din roll", "Tyck till"]),
  );
  // Min besättning's tabs are not on this page.
  expect(titles).not.toContain("Kullar och parningar");
  await expect(page.locator(".driver-popover")).toHaveCount(0);
});
