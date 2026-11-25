import { expect, type Page } from "@playwright/test";

export const inboxItemsForHerd = (page: Page, herd: string) =>
  page
    .getByRole("region", { name: "Ärendelista", exact: true })
    .getByRole("link")
    .filter({ has: page.getByText(herd, { exact: true }) });

export async function takePaperForm(page: Page, herd: string) {
  await page.goto(`/stamboken/inkorg?mode=nya&herd=${herd}`);
  // M9006 has two forms. Open the first one still waiting in the queue.
  await inboxItemsForHerd(page, herd).first().click();
  await page
    .getByRole("region", { name: "Valt ärende" })
    .getByRole("button", { name: "Börja registrera" })
    .click();
  await expect(page).toHaveURL(/\/stamboken\/inkorg\/\d+$/);
  const itemId = new URL(page.url()).pathname.split("/").pop();
  await page.getByRole("link", { name: "Mata in årsrapporten" }).click();
  await expect(page).toHaveURL(
    `/stamboken/arsrapport/${herd}/2025?post=${itemId}`,
  );
}
