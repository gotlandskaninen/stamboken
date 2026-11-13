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

  test("hero section renders with headline, price and member links", async ({
    page,
  }) => {
    const h1 = page.getByRole("heading", { level: 1 });
    await expect(h1).toContainText("Vi bevarar");
    await expect(h1).toContainText("gotlandskanin och mellerudskanin");

    const hero = page.locator(".landing-hero");
    await expect(hero.getByText(/200 kr om året/)).toBeVisible();
    await expect(
      hero.getByRole("link", { name: "Medlemsforum" }),
    ).toHaveAttribute("href", "/medlemsforum");

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

  test("mission section explains the gene bank and links on", async ({
    page,
  }) => {
    await expect(
      page.getByRole("heading", { level: 2, name: /Genbanken finns hemma/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: /Så fungerar genbanken/ }),
    ).toHaveAttribute("href", "/foreningen");
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

    const cards = page.locator(".breed-cards");
    await expect(
      cards.getByRole("link", { name: /Gotlandskanin/ }),
    ).toHaveAttribute("href", "/gotlandskanin");
    await expect(
      cards.getByRole("link", { name: /Mellerudskanin/ }),
    ).toHaveAttribute("href", "/mellerudskanin");
    await expect(cards.getByText(/genbanksbesättningar/)).toHaveCount(2);
  });

  test("EU section renders with the badge and what the support covers", async ({
    page,
  }) => {
    const euSection = page.locator("#eu-stod");
    await expect(
      euSection.getByRole("heading", {
        name: /Föreningen Gotlandskaninen får stöd/,
      }),
    ).toBeVisible();
    await expect(euSection.getByText(/genbanksintyg/)).toBeVisible();
    await expect(
      euSection.getByRole("img", {
        name: "Medfinansieras av Europeiska unionen",
      }),
    ).toBeVisible();
  });

  test("membership section lists what a member gets and ends with the price", async ({
    page,
  }) => {
    await expect(
      page.getByRole("heading", { name: /bevarandet/ }),
    ).toBeVisible();
    const body = page.locator(".member-body");
    await expect(body.getByRole("listitem")).toHaveCount(3);
    await expect(body.getByText(/200 kr om året/)).toBeVisible();
    await expect(
      body.getByRole("link", { name: /Bli medlem/ }),
    ).toHaveAttribute("href", "/bli-medlem");
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

  test("footer links to the privacy policy", async ({ page }) => {
    await page
      .locator("footer")
      .getByRole("link", { name: "Integritetspolicy" })
      .click();
    await expect(page).toHaveURL(/\/integritetspolicy$/);
    await expect(
      page.getByRole("heading", { level: 1, name: "Integritetspolicy" }),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { level: 2, name: "Dina rättigheter" }),
    ).toBeVisible();
    // Open decisions are marked with <mark>; the policy must not ship with any.
    await expect(page.locator("mark")).toHaveCount(0);
  });
});

test.describe("Landing page CTA above fold", () => {
  for (const viewport of VIEWPORTS) {
    test(`Bli medlem visible above fold at ${viewport.name} (${viewport.width}px)`, async ({
      page,
    }) => {
      await page.setViewportSize({
        width: viewport.width,
        height: viewport.height,
      });
      await page.goto("/", { waitUntil: "networkidle" });

      // The hero's own button: the nav link is inside a closed drawer on phones.
      const cta = page
        .locator("main")
        .getByRole("link", { name: /bli medlem/i })
        .first();
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
  test("links and buttons in the page body are at least 44px high on phones", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto("/", { waitUntil: "networkidle" });
    const small = await page.evaluate(() =>
      [...document.querySelectorAll("main a, main button")]
        .map((e) => ({
          text: (e.textContent ?? "").trim().slice(0, 30),
          height: Math.round(
            Math.max(
              e.getBoundingClientRect().height,
              ...[...e.children].map((c) => c.getBoundingClientRect().height),
            ),
          ),
        }))
        .filter((x) => x.height > 0 && x.height < 44),
    );
    expect(small).toEqual([]);
  });

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

    // Sections: mission, breeds, membership, EU
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
