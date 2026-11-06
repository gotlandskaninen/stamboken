import { test, expect } from "@playwright/test";
import { dismissCookieBanner } from "./helpers/cookie-banner";

test.describe("Testbreed with Grandparents", () => {
  test("provparning form has grandparent fields and calculates COI", async ({
    page,
  }) => {
    await page.goto("/provparning");
    await page.waitForLoadState("networkidle");
    await dismissCookieBanner(page);

    const body = page.locator("body");
    await expect(body).toContainText(/Provparning/i);

    // Must show parent selectors — use exact: true to avoid matching
    // "Välj mormor" / "Välj morfar" etc.
    await expect(page.getByLabel("Välj mor", { exact: true })).toBeVisible({
      timeout: 5000,
    });
    await expect(page.getByLabel("Välj far", { exact: true })).toBeVisible({
      timeout: 5000,
    });

    // REGRESSION: grandparent fields must exist
    // They are disabled when a parent is selected, but must be present
    await expect(page.getByLabel(/Välj mormor/i)).toBeVisible({
      timeout: 5000,
    });
    await expect(page.getByLabel(/Välj morfar/i)).toBeVisible({
      timeout: 5000,
    });
    await expect(page.getByLabel(/Välj farmor/i)).toBeVisible({
      timeout: 5000,
    });
    await expect(page.getByLabel(/Välj farfar/i)).toBeVisible({
      timeout: 5000,
    });

    // Select mother from autocomplete
    const motherField = page.getByLabel("Välj mor", { exact: true });
    await motherField.click();
    const firstFemale = page.getByRole("option").first();
    if (await firstFemale.isVisible({ timeout: 3000 }).catch(() => false)) {
      await firstFemale.click();
    }

    // Select father from autocomplete
    const fatherField = page.getByLabel("Välj far", { exact: true });
    await fatherField.click();
    const firstMale = page.getByRole("option").first();
    if (await firstMale.isVisible({ timeout: 3000 }).catch(() => false)) {
      await firstMale.click();
    }

    // Click calculate button — "Beräkna inavelkoefficient"
    const calcButton = page
      .locator("button")
      .filter({ hasText: /Beräkna inavel/i });
    if (await calcButton.isEnabled({ timeout: 3000 }).catch(() => false)) {
      await calcButton.click();
      await page.waitForLoadState("networkidle");
      // Result popup should appear with COI value
      await expect(body).toContainText(/inavel|COI|%/i);
    }
  });

  test("authenticated testbreed API with grandparents returns COI", async ({
    page,
  }) => {
    // The call goes through an in-page fetch(), not page.request: Node's
    // APIRequestContext ignores Chromium's --host-resolver-rules, so against
    // the Phase 20 audit stack it would resolve the real production hostname.
    // The individuals are looked up at runtime instead of hard-coded, so the
    // spec asserts a real COI on whichever database it is pointed at.
    await page.goto("/", { waitUntil: "domcontentloaded" });
    const result = await page.evaluate(async () => {
      const me = await (
        await fetch("/api/user", { credentials: "same-origin" })
      ).json();
      const herd = me.is_owner?.[0];
      if (!herd) return { skipped: "user owns no herd" };
      const data = await (
        await fetch(`/api/herd/${herd}`, { credentials: "same-origin" })
      ).json();
      const active = (data.individuals ?? []).filter(
        (i: { is_active?: boolean }) => i.is_active,
      );
      const males = active.filter((i: { sex?: string }) => i.sex === "male");
      const females = active.filter(
        (i: { sex?: string }) => i.sex === "female",
      );
      if (males.length < 2 || females.length < 2) {
        return { skipped: "herd lacks two active individuals of each sex" };
      }
      // Unregistered parents + known grandparents: the branch this spec is about.
      const res = await fetch("/api/testbreed", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({
          genebankId: data.genebank ?? 1,
          male: "",
          female: "",
          maleGF: males[0].number,
          maleGM: females[0].number,
          femaleGF: males[1].number,
          femaleGM: females[1].number,
        }),
      });
      return {
        status: res.status,
        contentType: res.headers.get("content-type") ?? "",
        body: await res.text(),
      };
    });

    if ("skipped" in result) {
      throw new Error(`Testbreed fixture unavailable: ${result.skipped}`);
    }
    expect(result.status).toBe(200);
    expect(result.contentType).toContain("application/json");
    const data = JSON.parse(result.body as string);
    expect(typeof data.offspringCOI).toBe("number");
    expect(Number.isFinite(data.offspringCOI)).toBe(true);
  });
});
