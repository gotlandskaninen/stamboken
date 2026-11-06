// Spec §7.3 self-lockout: as the SOLE admin, try to revoke own admin role,
// assert the 409 UX (§5.3 case 1 red banner). The local-production dump
// contains the real production admins, so the sole-admin precondition is
// created by temporarily DEACTIVATING every other active admin (the §4.10
// invariant counts only ACTIVE admins — rev 10) and restored afterwards.
// Deactivation is reversible by design (§4.12) and this stack is disposable.
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";
import {
  ROLE_REMOVE_ADMIN,
  SEARCH_FIELD,
  SELF_LOCKOUT_BANNER,
} from "./helpers/copy";
import { psql } from "./helpers/db";

test.describe("self-lockout guard (sole active admin)", () => {
  let benched: string[] = [];

  test.beforeAll(() => {
    const out = psql(
      "UPDATE hbuser SET is_active = false " +
        'WHERE privileges::jsonb @> \'[{"level": "admin"}]\' ' +
        "AND username <> 'test-admin' AND is_active " +
        "RETURNING username;",
    );
    benched = out ? out.split("\n").filter(Boolean) : [];
  });

  test.afterAll(() => {
    if (benched.length === 0) return;
    const list = benched.map((u) => `'${u.replace(/'/g, "''")}'`).join(", ");
    psql(`UPDATE hbuser SET is_active = true WHERE username IN (${list});`);
  });

  test("revoking own admin as sole admin shows the 409 red banner", async ({
    page,
    context,
  }) => {
    await loginAs(page, context, ADMIN, "prod");
    await page.goto("/stamboken/admin/anvandare");
    await page.getByRole("textbox", { name: SEARCH_FIELD }).fill("test-admin");
    await page.getByRole("link", { name: "test-admin", exact: true }).click();
    // Wait out the search-rerender/navigation race before reading the URL.
    await expect(page).toHaveURL(/\/stamboken\/admin\/anvandare\/\d+/);
    const detailUrl = page.url();

    // C12 renders privileges as list items with a visible "Ta bort" ghost
    // button, so the row is identified by that button's aria-label
    // ("Ta bort <roll>") instead of the old anchored whole-text match.
    // Revoking one's OWN admin entry always opens the §5.3 case-3 confirm
    // dialog first; confirming as the sole active admin trips the case-1
    // refusal (revokeRole pre-check + authoritative backend 409) → the
    // same red banner.
    const revokeAdmin = page.getByRole("button", {
      name: ROLE_REMOVE_ADMIN,
      exact: true,
    });
    await revokeAdmin.click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Ta bort rollen" })
      .click();
    await expect(page.getByText(SELF_LOCKOUT_BANNER)).toBeVisible();

    // The privilege survived — reload and confirm the admin entry is intact.
    await page.goto(detailUrl);
    await expect(revokeAdmin).toBeVisible();
  });
});
