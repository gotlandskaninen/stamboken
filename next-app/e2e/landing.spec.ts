import { test, expect } from "@playwright/test";

const VIEWPORTS = [
  { name: "mobile", width: 375, height: 812 },
  { name: "tablet", width: 768, height: 1024 },
  { name: "desktop", width: 1440, height: 900 },
] as const;

test.describe("Landing page sections", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });
  });

  test("hero section renders with headline and shortcuts", async ({ page }) => {
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toContainText("Vi bevarar");
    await expect(h1).toContainText("gotlandskanin och mellerudskanin");

    // Quick shortcuts card
    await expect(page.getByText("Snabbgenvägar")).toBeVisible();

    // The "nya Stamboken (beta)" notice is scoped to /stamboken-online and
    // the app; the association's landing page must not show it.
    await expect(page.getByText(/nya Stamboken \(beta\)/)).toHaveCount(0);
    await expect(
      page.getByRole("link", { name: /bli medlem/i }).first(),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /stamboken online/i }).first(),
    ).toBeVisible();
  });

  test("breeds section renders with both breeds", async ({ page }) => {
    await expect(
      page.getByRole("heading", { level: 2, name: /lantraskaninen\./ }),
    ).toBeVisible();

    await expect(
      page.getByRole("heading", { name: "Gotlandskanin", exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Mellerudskanin", exact: true }),
    ).toBeVisible();

    // Both breed cards have an endangered badge
    const breedCards = page.locator("article");
    await expect(breedCards.first()).toBeVisible();
    expect(
      await breedCards.filter({ hasText: "Utrotningshotad" }).count(),
    ).toBe(2);
  });

  test("EU section renders with support text and items", async ({ page }) => {
    const euSection = page.locator("#eu-stod");
    await expect(euSection).toBeVisible();

    await expect(
      euSection.getByText(/Föreningen Gotlandskaninen får stöd/),
    ).toBeVisible();

    // Spot-check a few EU items
    await expect(euSection.getByRole("listitem")).toHaveCount(8);
    await expect(euSection.getByText("Genbanksintyg")).toBeVisible();
  });

  test("CTA section renders with membership info", async ({ page }) => {
    await expect(
      page.getByRole("heading", { name: /bevarandet/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: /200 kr om året/ }),
    ).toBeVisible();
  });

  test("footer renders with EU logo and footer links", async ({ page }) => {
    const footer = page.locator("footer");
    await expect(footer).toBeVisible();

    await expect(
      footer.getByRole("img", {
        name: "Medfinansieras av Europeiska unionen",
      }),
    ).toBeVisible();
    await expect(
      footer.getByText("Föreningen Gotlandskaninen").first(),
    ).toBeVisible();
  });
});

test.describe("Landing page nav CTA above fold", () => {
  // Hero is tall on mobile (480px+), so "Bli medlem" nav button is above fold
  // only on tablet/desktop where the nav bar is visible.
  const aboveFoldViewports = VIEWPORTS.filter((v) => v.width >= 768);
  for (const viewport of aboveFoldViewports) {
    test(`Bli medlem visible above fold at ${viewport.name} (${viewport.width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize({
        width: viewport.width,
        height: viewport.height,
      });
      await page.goto("/", { waitUntil: "networkidle" });

      const cta = page.getByRole("link", { name: /bli medlem/i }).first();
      await expect(cta).toBeVisible();

      const box = await cta.boundingBox();
      expect(box).not.toBeNull();
      expect(box!.y + box!.height).toBeLessThan(viewport.height);
    });
  }
});

test.describe("Landing page viewport screenshots", () => {
  for (const viewport of VIEWPORTS) {
    test(`screenshot at ${viewport.name} (${viewport.width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize({
        width: viewport.width,
        height: viewport.height,
      });
      await page.goto("/", { waitUntil: "networkidle" });

      await expect(page.getByRole("heading", { level: 1 })).toBeVisible();

      await page.screenshot({
        path: `e2e/screenshots/landing-${viewport.name}.png`,
        fullPage: true,
      });
    });
  }
});

test.describe("Landing page responsive", () => {
  // ADR-0010 375-px-kravet: no horizontal scroll at the mobile breakpoint. Regression
  // for the fixed-56px h2 that let "lantraskaninen." push the page to 428px.
  test("no horizontal overflow at mobile (375px)", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/", { waitUntil: "networkidle" });
    const widths = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    expect(widths.scroll).toBe(widths.client);

    // Sections clip with overflow:hidden, so a too-wide grid track hides
    // content without scrolling: every section heading must end on-screen.
    const clipped = await page.evaluate(() =>
      [...document.querySelectorAll("main h2")]
        .filter((h) => h.getBoundingClientRect().right > window.innerWidth)
        .map((h) => h.textContent?.slice(0, 40)),
    );
    expect(clipped).toEqual([]);
  });
});

test.describe("Stamboken Online entry", () => {
  test("shows the beta notice", async ({ page }) => {
    await page.goto("/stamboken-online", { waitUntil: "networkidle" });
    await expect(page.getByText(/nya Stamboken \(beta\)/)).toBeVisible();
  });
});

test.describe("Landing page accessibility", () => {
  test("heading hierarchy: single h1, logical h2 nesting", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    const h1Elements = await page.getByRole("heading", { level: 1 }).all();
    expect(h1Elements).toHaveLength(1);

    // Sections: Pillars, Breeds, EU, Members, CTA = at least 4 h2s
    const h2Elements = await page.getByRole("heading", { level: 2 }).all();
    expect(h2Elements.length).toBeGreaterThanOrEqual(4);
  });

  test("all images have explicit alt attribute", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    const images = await page.locator("img").all();
    for (const img of images) {
      const alt = await img.getAttribute("alt");
      // alt="" is valid for decorative images; null means missing attribute
      expect(
        alt !== null,
        `Image missing alt attribute: ${await img.getAttribute("src")}`,
      ).toBe(true);
    }
  });

  test("interactive elements are keyboard focusable", async ({ page }) => {
    await page.goto("/", { waitUntil: "networkidle" });

    await page.keyboard.press("Tab");
    const focusedTag = await page.evaluate(() =>
      document.activeElement?.tagName.toLowerCase(),
    );
    expect(["a", "button", "input"]).toContain(focusedTag);
  });
});
