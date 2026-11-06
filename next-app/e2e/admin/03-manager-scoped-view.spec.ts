// Spec §7.3 manager-scoped-view: manager(GK) on /besattningar sees only GK
// herds; direct-URL to a herd outside their genebank → 404 (§1.3, §5.10).
import { test, expect } from "@playwright/test";
import { loginAs, MANAGER } from "./helpers/auth";
import { MANAGER_HERDS_NAV } from "./helpers/copy";
import { psql } from "./helpers/db";

test.describe("manager scoped herd view", () => {
  let mkHerdId: string;

  test.beforeAll(() => {
    // Numeric Herd.id (column herd_id) of any Mellerudskanin herd — outside
    // test-gk-manager's genebank. Genebank names per cli/create_test_users.py.
    mkHerdId = psql(
      "SELECT h.herd_id FROM herd h " +
        "JOIN genebank g ON h.genebank_id = g.genebank_id " +
        "WHERE g.name = 'Mellerudskanin' LIMIT 1;",
    );
    expect(mkHerdId).toMatch(/^\d+$/);
  });

  test.beforeEach(async ({ page, context }) => {
    await loginAs(page, context, MANAGER, "prod");
  });

  test("herd list is scoped to the manager's genebank", async ({ page }) => {
    await page.goto("/stamboken/admin/besattningar");
    // §2.2 manager nav variant proves the scoped view rendered.
    await expect(page.getByText(MANAGER_HERDS_NAV)).toBeVisible();
    // Fas C13: raderna är DataGrid-rader; besättningsnumret är en länk i
    // sin cell. Varje kod är en G-besättning (GK-prefix); inga M-koder läcker.
    await expect(
      page.getByRole("link", { name: /^G\d+/ }).first(),
    ).toBeVisible(); // at least one data row
    await expect(page.getByRole("link", { name: /^M\d+/ })).toHaveCount(0);
  });

  test("out-of-range page redirects to the last page", async ({ page }) => {
    // Codex terra-review PR #101: utan clamp blev ?page=<för högt> en tom
    // lista utan sidlänkar att ta sig tillbaka med.
    await page.goto("/stamboken/admin/besattningar?page=9999");
    await expect(page).not.toHaveURL(/page=9999/);
    await expect(
      page.getByRole("link", { name: /^G\d+/ }).first(),
    ).toBeVisible();
  });

  test("direct-URL to an outside herd is 404", async ({ page }) => {
    const res = await page.goto(`/stamboken/admin/besattningar/${mkHerdId}`);
    expect(res?.status()).toBe(404);
  });
});
