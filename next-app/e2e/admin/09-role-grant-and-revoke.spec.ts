// Spec §7.3 role-grant-and-revoke: grant owner(herd); revoke; verify two
// privileges audit rows (DB column name; `_privileges` is only the Python
// attribute — W2 C5). RolePicker (Task 26) submits numeric ids from
// the autocomplete — admins never type raw integers.
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN, VICTIM_ROLE } from "./helpers/auth";
import {
  ROLE_ADD_BUTTON,
  ROLE_HERD_FIELD,
  ROLE_LEVEL_FIELD,
  ROLE_REMOVE_BUTTON,
  SEARCH_FIELD,
} from "./helpers/copy";
import { psql } from "./helpers/db";

test("grant + revoke owner(herd) writes two privileges audit rows", async ({
  page,
  context,
}) => {
  // The empty GK herd (owned by test-empty) — its code drives the
  // autocomplete; granting a temporary second owner entry is reverted below.
  const herdCode = psql(
    "SELECT h.herd FROM herd h, hbuser u, " +
      "jsonb_array_elements(u.privileges::jsonb) e " +
      "WHERE u.username = 'test-empty' AND e->>'level' = 'owner' " +
      "AND h.herd_id = (e->>'herd')::int LIMIT 1;",
  );
  expect(herdCode).toMatch(/^G/);

  await loginAs(page, context, ADMIN, "prod");
  await page.goto("/stamboken/admin/anvandare");
  await page
    .getByRole("textbox", { name: SEARCH_FIELD })
    .fill(VICTIM_ROLE.username);
  await page
    .getByRole("link", { name: VICTIM_ROLE.username, exact: true })
    .click();
  // Wait out the search-rerender/navigation race before reading the URL
  // (same pattern as spec 05's edit-profile test).
  await expect(page).toHaveURL(/\/stamboken\/admin\/anvandare\/\d+/);
  const userId = page.url().match(/anvandare\/(\d+)/)![1];

  // Grant owner(herd) via RolePicker: level select + herd autocomplete
  // (Task 26 level labels: Admin / Genbanksansvarig / Granskare /
  // Besättningsägare).
  await page.getByLabel(ROLE_LEVEL_FIELD).click();
  await page.getByRole("option", { name: "Besättningsägare" }).click();
  await page.getByLabel(ROLE_HERD_FIELD, { exact: true }).fill(herdCode);
  await page
    .getByRole("option", { name: new RegExp(herdCode) })
    .first()
    .click();
  await page.getByRole("button", { name: ROLE_ADD_BUTTON }).click();

  // The new privilege entry renders on the (re-fetched) detail page — C12
  // renders each privilege as an <li> with a level badge + the resolved
  // target ("<code> — <namn>"), so anchor on the herd code, not on the
  // old composite "Besättningsägare — <code>" string.
  await page.goto(`/stamboken/admin/anvandare/${userId}`);
  const grantedEntry = page.getByRole("listitem").filter({ hasText: herdCode });
  await expect(grantedEntry.first()).toBeVisible();

  // Revoke the same entry (ghost button, aria-label "Ta bort <roll>").
  await grantedEntry
    .first()
    .getByRole("button", { name: ROLE_REMOVE_BUTTON })
    .click();
  await page.goto(`/stamboken/admin/anvandare/${userId}`);
  await expect(
    page.getByRole("listitem").filter({ hasText: herdCode }),
  ).toHaveCount(0);

  // Two privileges audit rows on this hbuser record (§7.3; Task C15's
  // field chips carry the Swedish label "Roller" for the DB column
  // `privileges`). The audit log accumulates across suite re-runs on the
  // same stack, so assert AT LEAST the pair this test just wrote rather
  // than an exact total.
  await page.goto(
    `/stamboken/admin/system/audit?table=hbuser&record_id=${userId}`,
  );
  expect(
    await page.getByText("Roller", { exact: true }).count(),
  ).toBeGreaterThanOrEqual(2);
});
