// Spec §7.3 ratelimit-status (rev 10 B5): the page renders enabled/storage
// fields and the registered-limits table. Local-production runs with
// RATELIMIT_ENABLED=false (CLAUDE.md), so `enabled` renders as the status
// strip's "Av" value with "Avstängt i konfigurationen" on the meta line
// below it (Task C14) — exactly the disabled case §7.3 pins ("works in
// local-production ... shows 'av'").
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";

test("renders enabled=Av, storage field and registered limits", async ({
  page,
  context,
}) => {
  await loginAs(page, context, ADMIN, "prod");
  await page.goto("/stamboken/admin/system/ratelimit");

  // enabled — local-production has RATELIMIT_ENABLED=false. Task C14's
  // status strip renders the value "Av" (serif) with the reason on its own
  // .sb-meta line under the label.
  await expect(page.getByText("Avstängt i konfigurationen")).toBeVisible();
  // storage — Task C14 translates the raw API value: redis → Redis,
  // memory → Minne (§3.3.4, parsed from RATELIMIT_STORAGE_URL).
  await expect(page.getByText(/Redis|Minne/).first()).toBeVisible();
  // Registered-limits table: the Flask-Limiter defaults from
  // app/extensions.py and the Task 20 admin reset limit, both formatted by
  // _lib/limitSv.ts ("1000 per 1 hour" → "1000 anrop per timme",
  // "10 per hour" → "10 anrop per timme").
  await expect(page.getByText("1000 anrop per timme").first()).toBeVisible();
  await expect(page.getByText("10 anrop per timme").first()).toBeVisible();
  // Funktion column shows the Swedish function label above the raw id.
  await expect(
    page.getByText("Standardgräns (alla anrop)").first(),
  ).toBeVisible();
  // Real table semantics survive the reskin (row 0 is the header).
  await expect(page.getByRole("row").nth(1)).toBeVisible();
});
