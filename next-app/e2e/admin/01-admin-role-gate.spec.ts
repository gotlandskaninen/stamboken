// Spec §7.3 admin-role-gate: owner → /stamboken/admin is a 404 (no admin
// nav, no card grid). §1.2/§5.10: role gate returns notFound(), never 403,
// for URL-enumeration hardening.
import { test, expect } from "@playwright/test";
import { loginAs, OWNER } from "./helpers/auth";
import { PANEL_HEADING } from "./helpers/copy";

test.describe("admin role gate — owner", () => {
  test.beforeEach(async ({ page, context }) => {
    await loginAs(page, context, OWNER, "prod");
  });

  test("owner gets 404 on the panel landing", async ({ page }) => {
    const res = await page.goto("/stamboken/admin");
    expect(res?.status()).toBe(404);
    await expect(
      page.getByRole("heading", { name: PANEL_HEADING }),
    ).toHaveCount(0);
  });

  test("owner gets 404 on every sub-page", async ({ page }) => {
    for (const path of [
      "/stamboken/admin/anvandare",
      "/stamboken/admin/besattningar",
      "/stamboken/admin/genbanker",
      "/stamboken/admin/system",
      "/stamboken/admin/system/audit",
    ]) {
      const res = await page.goto(path);
      expect(res?.status(), `${path} must 404 for owner`).toBe(404);
    }
  });
});
