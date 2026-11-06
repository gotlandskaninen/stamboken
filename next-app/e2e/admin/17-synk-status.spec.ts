// Spec §7.3 synk-status (rev 10 B3): seed a fresh + a stale
// demo_sync_status row; assert the page renders last-run data and the
// >26 h staleness banner respectively (§3.3.3). The endpoint computes
// `stale` from the NEWEST finished row, so the table is cleared between
// the two cases. demo_sync_status is NOT audited (§4.1.e) — plain
// INSERT/DELETE is safe. Rows seeded here carry detail='e2e-seed'.
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";
import { SYNC_STALE_BANNER } from "./helpers/copy";
import { psql } from "./helpers/db";

test.describe("demo-sync status page", () => {
  test.afterAll(() => {
    psql("DELETE FROM demo_sync_status WHERE detail = 'e2e-seed';");
  });

  test.beforeEach(async ({ page, context }) => {
    await loginAs(page, context, ADMIN, "prod");
  });

  test("fresh run renders last-run data, no staleness banner", async ({
    page,
  }) => {
    psql("DELETE FROM demo_sync_status;");
    psql(
      "INSERT INTO demo_sync_status (started_at, finished_at, success, detail, rows_synced) " +
        "VALUES (now() - interval '5 minutes', now() - interval '4 minutes', " +
        "true, 'e2e-seed', 1234);",
    );
    await page.goto("/stamboken/admin/system/synk");
    await expect(page.getByText("1234")).toBeVisible(); // rows_synced
    await expect(page.getByText(SYNC_STALE_BANNER)).toHaveCount(0);
  });

  test(">26 h old run renders the staleness banner", async ({ page }) => {
    psql("DELETE FROM demo_sync_status;");
    psql(
      "INSERT INTO demo_sync_status (started_at, finished_at, success, detail, rows_synced) " +
        "VALUES (now() - interval '28 hours', now() - interval '27 hours', " +
        "true, 'e2e-seed', 1200);",
    );
    await page.goto("/stamboken/admin/system/synk");
    await expect(page.getByText(SYNC_STALE_BANNER)).toBeVisible();
  });
});
