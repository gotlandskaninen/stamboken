// Spec §7.3 user-list-and-search: list users, filter by role=admin, assert
// the correct set. Extended with §3.1 search and the edit-profile flow
// (fullname; §2.5 post-mutation redirect to the list).
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN, VICTIM_PROFILE } from "./helpers/auth";
import { FULLNAME_FIELD, SAVE_BUTTON, SEARCH_FIELD } from "./helpers/copy";

test.describe("user list, search, filter, edit profile", () => {
  test.beforeEach(async ({ page, context }) => {
    await loginAs(page, context, ADMIN, "prod");
  });

  test("search narrows the list", async ({ page }) => {
    await page.goto("/stamboken/admin/anvandare");
    // A real prod dump paginates (25/page) — nothing guarantees test-admin
    // on page 1, so visibility is asserted through search from the start.
    // §2.6: plain GET form — Enter submits and puts search in the URL, so
    // each step waits on the URL instead of racing the live-filter debounce.
    const search = page.getByRole("textbox", { name: SEARCH_FIELD });
    await search.fill("test-admin");
    await search.press("Enter");
    await page.waitForURL(/search=test-admin/);
    await expect(
      page.getByRole("gridcell", { name: "test-admin", exact: true }),
    ).toBeVisible();

    await search.fill("test-gk-owner");
    await search.press("Enter");
    await page.waitForURL(/search=test-gk-owner/);
    await expect(
      page.getByRole("gridcell", { name: "test-gk-owner", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("gridcell", { name: "test-mk-owner", exact: true }),
    ).toHaveCount(0);
  });

  test("role=admin filter shows admins only", async ({ page }) => {
    // §3.3.1-style shareable URL params (§2.6 pagination convention) — the
    // list is server-rendered from query params.
    await page.goto("/stamboken/admin/anvandare?role=admin");
    await expect(
      page.getByRole("gridcell", { name: "test-admin", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("gridcell", { name: "test-gk-owner", exact: true }),
    ).toHaveCount(0);
  });

  test("edit profile saves and redirects to the list (§2.5)", async ({
    page,
  }) => {
    await page.goto("/stamboken/admin/anvandare");
    await page
      .getByRole("textbox", { name: SEARCH_FIELD })
      .fill(VICTIM_PROFILE.username);
    await page
      .getByRole("link", { name: VICTIM_PROFILE.username, exact: true })
      .click();
    await expect(page).toHaveURL(/\/stamboken\/admin\/anvandare\/\d+/);

    await page
      .getByRole("textbox", { name: FULLNAME_FIELD })
      .fill("Test MK Manager (E2E)");
    await page.getByRole("button", { name: SAVE_BUTTON }).click();

    // Post-mutation navigation: redirect to the parent list, never stay.
    await page.waitForURL(/\/stamboken\/admin\/anvandare(\?.*)?$/);
    await page
      .getByRole("textbox", { name: SEARCH_FIELD })
      .fill(VICTIM_PROFILE.username);
    await expect(
      page.getByRole("gridcell", { name: "Test MK Manager (E2E)" }),
    ).toBeVisible();

    // Restore.
    await page
      .getByRole("link", { name: VICTIM_PROFILE.username, exact: true })
      .click();
    await page
      .getByRole("textbox", { name: FULLNAME_FIELD })
      .fill("Test MK Manager");
    await page.getByRole("button", { name: SAVE_BUTTON }).click();
    await page.waitForURL(/\/stamboken\/admin\/anvandare(\?.*)?$/);
  });
});
