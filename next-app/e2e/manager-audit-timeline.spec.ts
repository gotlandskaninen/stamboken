import { test, expect } from "@playwright/test";
import { loginInline, TEST_USERS } from "../e2e-shared/auth";

// Auth is handled by storageState (gk-manager) set in playwright.config.ts.

const API_BASE = "http://localhost:9090";

// These tests require audit entries to exist, which means the audit triggers
// must have been active when seed data was loaded. In CI the triggers are
// created after seed data, so we skip unless AUDIT_E2E=1 is set.
const skip = !process.env.AUDIT_E2E;

test.describe("Audit Timeline — Manager view", () => {
  test.skip(() => skip, "Set AUDIT_E2E=1 to run (requires audit entries)");
  test.describe.configure({ timeout: 60000 });

  let testIndividualNumber: string;

  test.beforeAll(async ({ browser }) => {
    // Login as manager to Flask API and find an individual to test with
    const context = await browser.newContext();
    const page = await context.newPage();

    const loginRes = await page.request.post(`${API_BASE}/api/login`, {
      data: TEST_USERS.manager,
    });
    expect(loginRes.ok()).toBeTruthy();

    // Find the first available individual
    const listRes = await page.request.get(
      `${API_BASE}/api/individuals?per_page=1`,
    );
    expect(listRes.ok()).toBeTruthy();
    const listData = await listRes.json();
    const items = listData.items || listData;
    expect(Array.isArray(items) && items.length > 0).toBeTruthy();
    testIndividualNumber = items[0].number;

    // Make a change to generate audit entries
    await page.request.patch(
      `${API_BASE}/api/individual/${testIndividualNumber}`,
      {
        data: {
          individual: testIndividualNumber,
          name: "E2E-AuditSetup",
          herd: items[0].herd?.herd || items[0].origin_herd?.herd || "",
        },
      },
    );

    await context.close();
  });

  test("manager sees Ändringshistorik on individual detail", async ({
    page,
  }) => {
    await page.goto(`/stamboken/individ/${testIndividualNumber}`);

    const auditHeading = page.getByText("Ändringshistorik", { exact: true });
    await expect(auditHeading).toBeVisible({ timeout: 30000 });
  });

  test("audit timeline shows operation chips", async ({ page }) => {
    await page.goto(`/stamboken/individ/${testIndividualNumber}`);
    await expect(
      page.getByText("Ändringshistorik", { exact: true }),
    ).toBeVisible({ timeout: 30000 });

    // Should show at least one operation chip (Ändrad or Skapad)
    const chip = page
      .locator(".MuiChip-root")
      .filter({ hasText: /Ändrad|Skapad/ });
    await expect(chip.first()).toBeVisible({ timeout: 5000 });
  });

  test("owner does NOT see Ändringshistorik", async ({ page, context }) => {
    // Switch to owner role (non-manager)
    await loginInline(page, context, TEST_USERS.owner);

    await page.goto(`/stamboken/individ/${testIndividualNumber}`);
    // Wait for page content to render
    await expect(page.getByText(testIndividualNumber)).toBeVisible({
      timeout: 30000,
    });

    // Owner should NOT see audit section
    const auditHeading = page.getByText("Ändringshistorik", { exact: true });
    await expect(auditHeading).not.toBeVisible({ timeout: 5000 });
  });
});
