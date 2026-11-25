import { test, expect } from "@playwright/test";

// Next serves robots.txt only from the app root; in the (app) route group it
// answered 404 in prod.
test("robots.txt is served", async ({ request }) => {
  const res = await request.get("/robots.txt");
  expect(res.status()).toBe(200);
  expect(await res.text()).toContain("Disallow: /stamboken");
});
