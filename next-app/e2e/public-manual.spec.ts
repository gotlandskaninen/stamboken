import { test, expect } from "@playwright/test";

// The manual and the getting-started page are public: someone who cannot log
// in yet is exactly who needs them.

test("the manual renders with working anchors and screenshots", async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/stamboken-online/manual#logga-in");

  await expect(
    page.getByRole("heading", { level: 1, name: "Manual för Stamboken" }),
  ).toBeVisible();
  await expect(page.locator("h3#logga-in")).toBeInViewport();
  // The coverage gate's route markers stay out of the page.
  await expect(page.getByText("route: /")).toHaveCount(0);

  const shot = page.getByRole("img", { name: "Inloggningssidan" });
  await shot.scrollIntoViewIfNeeded();
  await expect
    .poll(() => shot.evaluate((img: HTMLImageElement) => img.naturalWidth))
    .toBeGreaterThan(0);

  // 375-px requirement (ADR-0010): wide tables scroll in their box.
  const scrollWidth = await page.evaluate(
    () => document.documentElement.scrollWidth,
  );
  expect(scrollWidth).toBeLessThanOrEqual(375);
});

test("getting started lists the steps and links to the manual", async ({
  page,
}) => {
  await page.goto("/stamboken-online/kom-igang");

  await expect(
    page.getByRole("heading", { level: 1, name: "Kom igång med Stamboken" }),
  ).toBeVisible();
  await expect(page.locator("main ol > li")).toHaveCount(6);

  await page.getByRole("link", { name: "Logga in steg för steg →" }).click();
  await expect(page).toHaveURL(/\/stamboken-online\/manual#logga-in$/);
  await expect(page.locator("h3#logga-in")).toBeInViewport();
});

test("the sign-in page points new users to getting started", async ({
  page,
}) => {
  await page.goto("/auth/sign-in");
  await page.getByRole("link", { name: "Kom igång →" }).click();
  await expect(page).toHaveURL(/\/stamboken-online\/kom-igang$/);
});
