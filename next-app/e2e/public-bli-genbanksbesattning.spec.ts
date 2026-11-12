import { test, expect } from "@playwright/test";

const VIEWPORTS = [
  { name: "mobile", width: 375, height: 812 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1440, height: 900 },
] as const;

const STEP_TITLES = [
  "Bli medlem",
  "Kontakta genbanksansvarig",
  "Skaffa startdjur",
  "Skicka in ansökan",
  "Godkännande",
];

test.describe("Bli genbanksbesättning", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/bli-genbanksbesattning", { waitUntil: "networkidle" });
  });

  test("header renders with the page title", async ({ page }) => {
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toBeVisible();
    // The rendered title carries a soft hyphen (U+00AD) so the compound word
    // may break on a 375px screen — compare against the stripped text.
    const rendered = (await h1.textContent()) ?? "";
    expect(rendered.replace(/\u00AD/g, "")).toBe("Bli genbanksbesättning");
  });

  test("the five steps are listed under 'Så går det till'", async ({
    page,
  }) => {
    await expect(
      page.getByRole("heading", { level: 2, name: "Så går det till" }),
    ).toBeVisible();

    const steps = page.locator("main ol > li");
    await expect(steps).toHaveCount(STEP_TITLES.length);

    for (const [i, title] of STEP_TITLES.entries()) {
      await expect(steps.nth(i).getByRole("heading", { level: 3 })).toHaveText(
        title,
      );
    }
  });

  test("both gene-bank managers are reachable by mail", async ({ page }) => {
    for (const address of [
      "gotlandskanin@gotlandskaninen.se",
      "mellerudskanin@gotlandskaninen.se",
    ]) {
      await expect(
        page.locator(`a[href="mailto:${address}"]`).first(),
      ).toBeVisible();
    }
  });

  test("links on to membership and the herdbook", async ({ page }) => {
    // Scoped to <main>: nav and footer carry the same hrefs.
    const main = page.getByRole("main");
    await expect(main.locator('a[href="/bli-medlem"]').first()).toBeVisible();
    await expect(
      main.locator('a[href="/stamboken-online"]').first(),
    ).toBeVisible();
  });
});

test("the old address redirects to the page", async ({ page }) => {
  await page.goto("/bli-genbank");
  await expect(page).toHaveURL(/\/bli-genbanksbesattning$/);
});

// ADR-0010 375-px-kravet: no horizontal scroll on any of the three breakpoints.
test.describe("Bli genbanksbesättning responsive", () => {
  for (const viewport of VIEWPORTS) {
    test(`no horizontal overflow at ${viewport.name} (${viewport.width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize({
        width: viewport.width,
        height: viewport.height,
      });
      await page.goto("/bli-genbanksbesattning", { waitUntil: "networkidle" });

      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

      const widths = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        inner: window.innerWidth,
      }));
      expect(widths.scroll).toBeLessThanOrEqual(widths.inner);
    });
  }
});
