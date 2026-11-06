// Spec §7.3 manager-escalation-blocked: manager direct-URLs /anvandare → 404.
// Extended per the §1.3 tier table: every admin-only sub-page 404s for a
// manager (anvandare, system and all four system tools).
import { test, expect } from "@playwright/test";
import { loginAs, MANAGER } from "./helpers/auth";

test("manager gets 404 on every admin-only page", async ({ page, context }) => {
  await loginAs(page, context, MANAGER, "prod");
  for (const path of [
    "/stamboken/admin/anvandare",
    "/stamboken/admin/system",
    "/stamboken/admin/system/audit",
    "/stamboken/admin/system/online",
    "/stamboken/admin/system/synk",
    "/stamboken/admin/system/ratelimit",
  ]) {
    const res = await page.goto(path);
    expect(res?.status(), `${path} must 404 for manager`).toBe(404);
  }
});
