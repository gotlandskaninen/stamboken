// Spec §7.3 audit-log-viewer: filters compose (table + date range); row
// expand shows old_data/new_data blocks; the viewer NEVER renders a
// password_hash/auth_data value even when the DB is seeded with a bogus
// row containing one — the §4.7 belt-and-suspenders SENSITIVE_AUDIT_KEYS
// strip at render time, independent of migration completeness.
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";
import { psql } from "./helpers/db";

const BOGUS_HASH = "BOGUS-HASH-SHOULD-NEVER-RENDER";
const BOGUS_AUTH = "BOGUS-AUTHDATA-SHOULD-NEVER-RENDER";

test.describe("audit-log viewer", () => {
  test.beforeAll(() => {
    // Simulates a pre-migration row that still carries credential material.
    psql(
      "INSERT INTO audit_log (table_name, record_id, operation, new_data, " +
        "changed_fields, changed_by) VALUES ('hbuser', 'e2e-bogus-1', 'UPDATE', " +
        `'{"fullname": "E2E Bogus", "password_hash": "${BOGUS_HASH}", ` +
        `"auth_data": "${BOGUS_AUTH}"}'::jsonb, ` +
        "ARRAY['fullname'], 'e2e-seed');",
    );
  });

  test.afterAll(() => {
    // Best-effort: Phase 4 protects audit_log against UPDATE via the
    // audit_log_no_update rule; if DELETE is similarly guarded the seeded
    // row simply stays in this disposable stack.
    try {
      psql("DELETE FROM audit_log WHERE changed_by = 'e2e-seed';");
    } catch {
      /* acceptable — see comment above */
    }
  });

  test("filters compose and sensitive keys are stripped at render", async ({
    page,
    context,
  }) => {
    await loginAs(page, context, ADMIN, "prod");
    const today = new Date().toISOString().slice(0, 10);

    // §3.3.1: server-rendered viewer with shareable URL params — table +
    // date-range + changed_by compose.
    await page.goto(
      `/stamboken/admin/system/audit?table=hbuser&changed_by=e2e-seed&from=${today}`,
    );
    // Task C15: the collapsed row is a real <button aria-expanded> whose
    // accessible name concatenates op badge + row title + field chips + meta.
    // .first() because beforeAll re-seeds the row on every retry/re-run.
    const seededRow = page
      .getByRole("button", { name: /Användare #e2e-bogus-1/ })
      .first();
    await expect(seededRow).toBeVisible();

    // Expand → Swedish field-label chip + diff table (the raw column name
    // "fullname" is translated to "Fullständigt namn"; both the chip and the
    // diff row render it, hence .first()).
    await seededRow.click();
    await expect(page.getByText("Fullständigt namn").first()).toBeVisible();

    // Raw JSON is behind the forensics toggle now, never the default view.
    await page.getByRole("button", { name: "Visa rådata" }).first().click();
    await expect(page.locator("pre").first()).toBeVisible();

    // The belt-and-suspenders check: neither the bogus values NOR the
    // sensitive keys render anywhere on the page (§4.7).
    const content = await page.content();
    expect(content).not.toContain(BOGUS_HASH);
    expect(content).not.toContain(BOGUS_AUTH);
    expect(content).not.toContain("password_hash");
    expect(content).not.toContain("auth_data");
  });

  test("table filter excludes other tables", async ({ page, context }) => {
    await loginAs(page, context, ADMIN, "prod");
    await page.goto("/stamboken/admin/system/audit?table=hbuser");
    // No genebank/herd rows leak into an hbuser-filtered view (row headers
    // render as "<table> #<record>").
    await expect(page.getByText(/Genbanker #/)).toHaveCount(0);
    await expect(page.getByText(/\bBesättningar #/)).toHaveCount(0);
  });
});
