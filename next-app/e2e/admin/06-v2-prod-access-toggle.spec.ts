// Spec §7.3 v2-prod-access-toggle: toggle the flag, then verify the audit
// row in /system/audit with the correct changed_by. Extended with the
// validated toggle (rev 10 A4 dedicated endpoint) — same page, same audit
// contract (§4.6). Both flags are toggled back to leave the stack clean.
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN, VICTIM_PROFILE } from "./helpers/auth";
import { SEARCH_FIELD, V2_TOGGLE, VALIDATED_TOGGLE } from "./helpers/copy";

test.describe("flag toggles audit to hbuser", () => {
  test.beforeEach(async ({ page, context }) => {
    await loginAs(page, context, ADMIN, "prod");
  });

  async function openVictimDetail(page: import("@playwright/test").Page) {
    await page.goto("/stamboken/admin/anvandare");
    await page
      .getByRole("textbox", { name: SEARCH_FIELD })
      .fill(VICTIM_PROFILE.username);
    await page
      .getByRole("link", { name: VICTIM_PROFILE.username, exact: true })
      .click();
    await expect(page).toHaveURL(/\/stamboken\/admin\/anvandare\/\d+/);
  }

  test("v2_prod_access toggle writes an audit row with changed_by", async ({
    page,
  }) => {
    await openVictimDetail(page);
    // MUI <Switch> renders an <input type="checkbox"> — the accessible
    // role is "checkbox" (Task 26's Flaggor switches).
    await page.getByRole("switch", { name: V2_TOGGLE }).click();

    // §3.3.1: viewer is server-rendered with shareable URL params.
    await page.goto(
      "/stamboken/admin/system/audit?table=hbuser&changed_by=test-admin",
    );
    // Task C15's viewer renders each row as a <button aria-expanded> with an
    // operation badge, the rowTitle and Swedish field-label chips. Rows are
    // sorted changed_at DESC, so .first() is the change this test just made.
    const newest = page.getByRole("button", { name: /Användare #\d+/ }).first();
    await expect(newest).toBeVisible();
    await newest.click(); // expand — field diff table (§3.3.1)
    // v2_prod_access → "Riktiga stamboken" (FIELD_LABELS).
    await expect(page.getByText("Riktiga stamboken").first()).toBeVisible();

    // Toggle back (restore).
    await openVictimDetail(page);
    await page.getByRole("switch", { name: V2_TOGGLE }).click();
  });

  test("validated toggle audits via the dedicated endpoint", async ({
    page,
  }) => {
    await openVictimDetail(page);
    await page.getByRole("switch", { name: VALIDATED_TOGGLE }).click();

    await page.goto(
      "/stamboken/admin/system/audit?table=hbuser&changed_by=test-admin",
    );
    await page
      .getByRole("button", { name: /Användare #\d+/ })
      .first()
      .click();
    // validated → "Webbkurs genomförd" (FIELD_LABELS).
    await expect(
      page.getByText("Webbkurs genomförd", { exact: true }).first(),
    ).toBeVisible();

    await openVictimDetail(page);
    await page.getByRole("switch", { name: VALIDATED_TOGGLE }).click(); // restore
  });
});
