// Spec §7.3 online-users-widget: test-admin appears in the widget within
// 30 s of login; toggle 1min / 5min / 15min (§3.3.2 — last_active window).
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";

test("freshly logged-in admin appears; window toggles work", async ({
  page,
  context,
}) => {
  await loginAs(page, context, ADMIN, "prod"); // login bumps last_active
  await page.goto("/stamboken/admin/system/online");

  // Task C14 renders the list as a real table: one row per user with
  // separate cells for användarnamn / namn / senast aktiv. The locator is
  // lazy, so the same const re-resolves after each window switch.
  const adminRow = page
    .getByRole("row")
    .filter({ hasText: "test-admin" })
    .first();

  // Default window 5 min — the just-logged-in admin is listed.
  await expect(
    adminRow.getByRole("cell", { name: "Test Admin" }),
  ).toBeVisible();

  // Toggle 15 min and 1 min (pill links ?minutes=) — still within both.
  await page.getByRole("link", { name: "15 min" }).click();
  await expect(
    adminRow.getByRole("cell", { name: "Test Admin" }),
  ).toBeVisible();
  await page.getByRole("link", { name: "1 min" }).click();
  await expect(
    adminRow.getByRole("cell", { name: "test-admin" }),
  ).toBeVisible();
});
