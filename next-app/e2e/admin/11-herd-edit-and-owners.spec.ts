// Herd list/filter view + herd metadata edit (§3.2) + the read-only owner
// section. Owner REASSIGN was removed 2026-08-04 (Jonas): a herd can have
// several owners (legacy parity — museum herds, shared family herds) and the
// old single-owner "Byt ägare" control silently dropped co-owners. Ownership
// is managed as roles on the USER page (spec 09 covers grant/revoke); the
// herd page only DISPLAYS the owners.
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";
import { SAVE_BUTTON } from "./helpers/copy";
import { psql } from "./helpers/db";

test.describe("herd list, edit, owner display", () => {
  let herdId: string;
  let herdCode: string;

  test.beforeAll(() => {
    // The empty GK herd owned by test-empty (bootstrap fixture).
    herdId = psql(
      "SELECT (e->>'herd')::int FROM hbuser u, " +
        "jsonb_array_elements(u.privileges::jsonb) e " +
        "WHERE u.username = 'test-empty' AND e->>'level' = 'owner' LIMIT 1;",
    );
    expect(herdId).toMatch(/^\d+$/);
    herdCode = psql(`SELECT herd FROM herd WHERE herd_id = ${Number(herdId)};`);
    expect(herdCode).toMatch(/^[A-Z]/);
  });

  test.beforeEach(async ({ page, context }) => {
    await loginAs(page, context, ADMIN, "prod");
  });

  test("admin list shows all genebanks and the filters narrow it", async ({
    page,
  }) => {
    // Fas C13: listan är en MUI DataGrid — besättningsnumret är en länk i
    // sin cell, genbanksnamnet är en egen cell (role "gridcell", inte "cell").
    await page.goto("/stamboken/admin/besattningar");
    await expect(
      page.getByRole("gridcell", { name: /Gotlandskanin/ }).first(),
    ).toBeVisible();
    await page.goto("/stamboken/admin/besattningar?genebank_id=2");
    await expect(
      page.getByRole("gridcell", { name: /Mellerudskanin/ }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("gridcell", { name: /Gotlandskanin/ }),
    ).toHaveCount(0);

    // Free-text search (2026-08-04): finds a specific herd by its code —
    // the spec's name-sort + no-search made that impossible on real data.
    await page.goto(`/stamboken/admin/besattningar?q=${herdCode}`);
    // `herdCode` is a bootstrap-seeded herd code (regex-safe).
    // nosemgrep: detect-non-literal-regexp
    await expect(
      page.getByRole("link", { name: new RegExp(herdCode) }).first(),
    ).toBeVisible();
  });

  test("herd metadata edit saves and redirects to the list (§2.5)", async ({
    page,
  }) => {
    const original = psql(
      `SELECT COALESCE(herd_name, '') FROM herd WHERE herd_id = ${Number(herdId)};`,
    );
    await page.goto(`/stamboken/admin/besattningar/${herdId}`);
    await page
      .getByRole("textbox", { name: /Besättningsnamn|Namn/ })
      .fill("E2E-redigerad");
    await page.getByRole("button", { name: SAVE_BUTTON }).click();
    await page.waitForURL(/\/stamboken\/admin\/besattningar(\?.*)?$/);

    // Restore.
    await page.goto(`/stamboken/admin/besattningar/${herdId}`);
    await page
      .getByRole("textbox", { name: /Besättningsnamn|Namn/ })
      .fill(original);
    await page.getByRole("button", { name: SAVE_BUTTON }).click();
    await page.waitForURL(/\/stamboken\/admin\/besattningar(\?.*)?$/);
  });

  test("herd detail lists every owner read-only with a link to the user page", async ({
    page,
  }) => {
    const ownerUserId = psql(
      "SELECT user_id FROM hbuser WHERE username = 'test-empty';",
    );
    // User-facing URL carries the herd CODE (2026-08-04) — the numeric-id
    // form in the edit test above stays accepted for backward compat.
    await page.goto(`/stamboken/admin/besattningar/${herdCode}`);

    // The owner renders as a LINK to the admin user page — ownership is
    // edited there (RolePicker), never on the herd page.
    const ownerLink = page.getByRole("link", { name: "test-empty" });
    await expect(ownerLink).toBeVisible();
    await expect(ownerLink).toHaveAttribute(
      "href",
      `/stamboken/admin/anvandare/${ownerUserId}`,
    );

    // No mutation control exists on the herd page.
    await expect(page.getByRole("button", { name: /Byt ägare/ })).toHaveCount(
      0,
    );

    // The owner usernames also render in the admin herd list row —
    // search narrows to THIS herd (a bare has_owner filter paginates it
    // onto a later page).
    await page.goto(`/stamboken/admin/besattningar?q=${herdCode}`);
    await expect(page.getByText("test-empty").first()).toBeVisible();
  });
});
