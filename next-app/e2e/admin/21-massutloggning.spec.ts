// Spec §7.3 massutloggning (rev 10 B4).
//
// ⚠️ MUST RUN LAST (highest filename prefix + workers:1 — see the config
// header). POST /api/v2/admin/sessions/mass-logout SCAN+DELetes EVERY
// session:* key in Redis db 2, including the sessions of any spec that
// would run after it AND the acting admin's own session. This spec
// re-logs-in at the end for its own audit-marker assertion; nothing may
// run after it without a fresh login of its own.
//
// Flow (§3.3.2): confirm flow requires typing LOGGA UT ALLA; after
// confirming, the admin lands on the login page (own session cleared too);
// a second, independent session (owner) dies as well; the endpoint wrote
// an audit marker row (record_id 'mass-logout-<utc>', operation SYSTEM).
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN, OWNER } from "./helpers/auth";
import {
  CONFIRM_BUTTON,
  MASS_LOGOUT_BUTTON,
  MASS_LOGOUT_PHRASE,
  MASS_LOGOUT_WARNING,
} from "./helpers/copy";

test("type-to-confirm mass logout kills every session and writes a marker", async ({
  page,
  context,
  browser,
}) => {
  // Second, independent session that must die with everyone else.
  const ctx2 = await browser.newContext({ ignoreHTTPSErrors: true });
  const page2 = await ctx2.newPage();
  await loginAs(page2, ctx2, OWNER, "prod");
  await page2.goto("/stamboken/min-besattning");
  expect(page2.url()).not.toContain("/auth/sign-in"); // session alive

  await loginAs(page, context, ADMIN, "prod");
  await page.goto("/stamboken/admin/system/online");
  await page.getByRole("button", { name: MASS_LOGOUT_BUTTON }).click();

  // §3.3.2 verbatim warning + type-to-confirm: the confirm button is
  // disabled until the admin types LOGGA UT ALLA.
  const dialog = page.getByRole("dialog");
  await expect(dialog.getByText(MASS_LOGOUT_WARNING)).toBeVisible();
  const confirm = dialog.getByRole("button", { name: CONFIRM_BUTTON });
  await expect(confirm).toBeDisabled();
  await dialog.getByRole("textbox").fill(MASS_LOGOUT_PHRASE);
  await expect(confirm).toBeEnabled();
  await confirm.click();

  // The admin's own session was cleared → lands on the login page.
  await page.waitForURL(/\/auth\/sign-in/);

  // The independent owner session died too.
  await page2.goto("/stamboken/min-besattning");
  await page2.waitForURL(/\/auth\/sign-in/);
  await ctx2.close();

  // Re-login (fresh session) and verify the audit marker via the read API —
  // marker shape per §3.3.2: record_id 'mass-logout-<utc>', SYSTEM,
  // new_data {"sessions_cleared": n}, changed_by = acting admin.
  await loginAs(page, context, ADMIN, "prod");
  const res = await page.request.get(
    "/api/v2/admin/audit-log?table=hbuser&changed_by=test-admin",
  );
  expect(res.ok()).toBeTruthy();
  const body = await res.text();
  expect(body).toContain("mass-logout-");
  expect(body).toContain("sessions_cleared");
});
