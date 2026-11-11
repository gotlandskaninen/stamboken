import { test, expect } from "@playwright/test";

// Needs the seeded CMS pages (docs/local-cms-testing.md).
test.describe("Next steps block on CMS pages", () => {
  test("a breed page ends with a way to join", async ({ page }) => {
    await page.goto("/gotlandskanin", { waitUntil: "networkidle" });
    const block = page.getByRole("complementary", { name: "Nästa steg" });
    await expect(
      block.getByRole("link", { name: /Bli medlem/ }),
    ).toHaveAttribute("href", "/bli-medlem");
    await expect(
      block.getByRole("link", { name: /Rasram för gotlandskanin/ }),
    ).toHaveAttribute("href", "/rasram-gotlandskanin");
  });

  test("the membership page ends with the application button", async ({
    page,
  }) => {
    await page.goto("/bli-medlem", { waitUntil: "networkidle" });
    await expect(
      page
        .getByRole("complementary", { name: "Nästa steg" })
        .getByRole("link", { name: /Ansök om medlemskap/ }),
    ).toHaveAttribute("href", "/ansok");
  });
});
