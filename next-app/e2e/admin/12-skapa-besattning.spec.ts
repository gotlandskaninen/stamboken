// Spec §7.3 skapa-besattning (rev 10 B2): create a herd via /besattningar/ny
// (genebank picker + manual letter-prefixed ID); assert it was created
// (detail page); retry with the same ID → Swedish duplicate-ID field
// error (§3.2).
// The created herd is soft-deleted (is_active=false) afterwards — hard
// delete does not exist by design (§3.2).
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";
import {
  DUPLICATE_HERD_ERROR,
  GENEBANK_FIELD,
  HERD_NAME_FIELD,
  HERD_NUMBER_FIELD,
  CREATE_HERD_BUTTON,
} from "./helpers/copy";
import { psql } from "./helpers/db";

test("create herd, list shows it, duplicate ID rejected in Swedish", async ({
  page,
  context,
}) => {
  // Pick a G-number that is free in the DB (manual IDs, no auto-numbering —
  // §3.2). Derived from the clock, verified against the herd table.
  let num = Number(Date.now().toString().slice(-6));
  while (psql(`SELECT 1 FROM herd WHERE herd = 'G${num}';`) === "1") num += 1;
  const code = `G${num}`;

  await loginAs(page, context, ADMIN, "prod");
  await page.goto("/stamboken/admin/besattningar/ny");
  await page.getByLabel(GENEBANK_FIELD).click();
  await page.getByRole("option", { name: "Gotlandskanin" }).click();
  await page
    .getByRole("textbox", { name: HERD_NUMBER_FIELD })
    .fill(String(num));
  await page
    .getByRole("textbox", { name: HERD_NAME_FIELD, exact: true })
    .fill("E2E Testbesättning");
  await page.getByRole("button", { name: CREATE_HERD_BUTTON }).click();

  // Post-create redirect per §2.5 lands on the list; the list has no
  // free-text search (Task 27), so the created herd is verified via its
  // detail page (id resolved from the DB).
  await page.waitForURL(/\/stamboken\/admin\/besattningar(\?.*)?$/);
  const newId = psql(`SELECT herd_id FROM herd WHERE herd = '${code}';`);
  expect(newId).toMatch(/^\d+$/);
  await page.goto(`/stamboken/admin/besattningar/${newId}`);
  await expect(page.getByText(code).first()).toBeVisible();

  // Same ID again → Swedish duplicate field error, no navigation.
  await page.goto("/stamboken/admin/besattningar/ny");
  await page.getByLabel(GENEBANK_FIELD).click();
  await page.getByRole("option", { name: "Gotlandskanin" }).click();
  await page
    .getByRole("textbox", { name: HERD_NUMBER_FIELD })
    .fill(String(num));
  await page
    .getByRole("textbox", { name: HERD_NAME_FIELD, exact: true })
    .fill("E2E Dubblett");
  await page.getByRole("button", { name: CREATE_HERD_BUTTON }).click();
  await expect(page.getByText(DUPLICATE_HERD_ERROR)).toBeVisible();
  expect(page.url()).toContain("/besattningar/ny");

  // Cleanup: soft-delete the created herd so repeated runs don't pile up
  // active E2E herds (owner pickers elsewhere exclude inactive herds, §3.2).
  psql(`UPDATE herd SET is_active = false WHERE herd = '${code}';`);
});
