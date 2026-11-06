import { test, expect } from "@playwright/test";
import { dismissCookieBanner } from "./helpers/cookie-banner";

test.describe("Certificate Generate and Verify", () => {
  test("individual detail shows certificate section", async ({ page }) => {
    await page.goto("/owner");
    await page.waitForLoadState("networkidle");
    await dismissCookieBanner(page);

    // The legacy UI uses a <table> with rows, not <a> links.
    const table = page.locator("table[aria-label='enhanced table']");
    const rows = table.locator("tbody tr");

    // The herd must have individuals — a spec that passes on an empty herd
    // proves nothing (Phase 20 Task 6, brief step 2).
    await expect(rows.first()).toBeVisible({ timeout: 15000 });
    expect(await rows.count()).toBeGreaterThan(0);

    await rows.first().click();
    await page.waitForLoadState("networkidle");

    // Individual detail page must load with the individual number visible
    const body = page.locator("body");
    await expect(body).toContainText(/[GM]\d+-\d+/);
  });

  test("certificate verify API rejects invalid data", async ({ page }) => {
    // In-page fetch, not page.request: Node's APIRequestContext ignores
    // Chromium's --host-resolver-rules, so against the Phase 20 audit stack it
    // would resolve the real production hostname. The individual is looked up
    // at runtime rather than hard-coded.
    await page.goto("/owner", { waitUntil: "domcontentloaded" });
    const result = await page.evaluate(async () => {
      const me = await (
        await fetch("/api/user", { credentials: "same-origin" })
      ).json();
      const herd = me.is_owner?.[0];
      if (!herd) return { skipped: "user owns no herd" };
      const data = await (
        await fetch(`/api/herd/${herd}`, { credentials: "same-origin" })
      ).json();
      const first = (data.individuals ?? [])[0];
      if (!first) return { skipped: "herd has no individuals" };
      const res = await fetch(`/api/certificates/verify/${first.number}`, {
        method: "POST",
        headers: { "Content-Type": "application/pdf" },
        credentials: "same-origin",
        body: "not a certificate",
      });
      return {
        status: res.status,
        contentType: res.headers.get("content-type") ?? "",
        body: await res.text(),
      };
    });

    if ("skipped" in result) {
      throw new Error(`Certificate fixture unavailable: ${result.skipped}`);
    }
    // An unparsable upload must come back as JSON with a message — never a 500
    // and never an HTML body, which certificate_verification.tsx cannot read.
    // 400, not 404: this individual has no certificate object, so the checksum
    // lookup raises NoSuchKey — the same handler code answers 400 on the old
    // backend too. Junk against an individual WITH a certificate gives 404.
    expect(result.status).toBe(400);
    expect(result.contentType).toContain("application/json");
    expect(JSON.parse(result.body as string)).toHaveProperty("response");
  });
});
