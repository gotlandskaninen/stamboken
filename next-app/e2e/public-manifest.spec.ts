import { test, expect } from "@playwright/test";

// Installing the app used the legacy manifest, whose start_url "." is
// /static/: a redirect loop on the public host (#220).
test("pages link the Stamboken manifest, which opens the dashboard", async ({
  page,
  request,
}) => {
  await page.goto("/");
  const link = page.locator('link[rel="manifest"]');
  await expect(link).toHaveCount(1);
  await expect(link).toHaveAttribute("href", "/manifest.webmanifest");

  const res = await request.get("/manifest.webmanifest");
  expect(res.ok()).toBe(true);
  expect((await res.json()).start_url).toBe("/stamboken/min-besattning");
});
