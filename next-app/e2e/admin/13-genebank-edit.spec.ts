// Spec §7.3 genebank-edit: edit the genebank NAME as admin; verify the
// audit row (the genebank table gets its FIRST audit trigger in migration
// 20→21 — §4.1.b). Original value restored afterwards.
// (The signatory field was removed 2026-08-04 — certificates are attested
// per individual by the issuing user, never at genebank level.)
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";
import { SAVE_BUTTON } from "./helpers/copy";
import { psql } from "./helpers/db";

test("genebank name edit saves and audits on the genebank table", async ({
  page,
  context,
}) => {
  const gbId = psql(
    "SELECT genebank_id FROM genebank WHERE name = 'Gotlandskanin';",
  );

  await loginAs(page, context, ADMIN, "prod");
  await page.goto(`/stamboken/admin/genbanker/${gbId}`);
  // "Gotlandskanin E2E" keeps every /Gotlandskanin/ substring assertion in
  // other specs alive even if a mid-test failure skips the restore below.
  await page.getByRole("textbox", { name: "Namn" }).fill("Gotlandskanin E2E");
  await page.getByRole("button", { name: SAVE_BUTTON }).click();
  await page.waitForURL(/\/stamboken\/admin\/genbanker(\?.*)?$/);

  // Audit row on table_name='genebank' with changed_fields containing
  // name (§4.1.b — trigger attached by migration 21). Task C15 renders the
  // row as a toggle button and translates the field name to "Namn".
  await page.goto("/stamboken/admin/system/audit?table=genebank");
  await page
    .getByRole("button", { name: /Genbanker #\d+/ })
    .first()
    .click();
  await expect(page.getByText("Namn", { exact: true }).first()).toBeVisible();
  await expect(page.getByText(/test-admin/).first()).toBeVisible();

  // Restore.
  await page.goto(`/stamboken/admin/genbanker/${gbId}`);
  await page.getByRole("textbox", { name: "Namn" }).fill("Gotlandskanin");
  await page.getByRole("button", { name: SAVE_BUTTON }).click();
  await page.waitForURL(/\/stamboken\/admin\/genbanker(\?.*)?$/);
});
