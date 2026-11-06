import { test, expect } from "@playwright/test";
import { loginInline } from "../e2e-shared/auth";

const MEMBER = { username: "test-member", password: "test-member-pass" };
const FAMILY = { username: "test-family", password: "test-family-pass" };
const ADMIN = { username: "test-admin", password: "test-admin-pass" };

test.describe("/stamboken/profil", () => {
  test("shows all five cards for a huvudmedlem and round-trips contact incl. postnummer", async ({
    page,
    context,
  }) => {
    await loginInline(page, context, MEMBER);
    await page.goto("/stamboken/profil");
    for (const name of [
      "Konto",
      "Medlemskap",
      "Kontaktuppgifter",
      "Publicering i Koharen",
      "Personer i medlemskapet",
    ]) {
      // exact — "Medlemskap" is a substring of "Personer i medlemskapet".
      await expect(
        page.getByRole("heading", { name, exact: true }),
      ).toBeVisible();
    }
    const stamp = String(Date.now()).slice(-5);
    await page.getByLabel("Gatuadress").fill(`Testgatan ${stamp}`);
    await page.getByLabel("Postnummer").fill("62355");
    await page.getByLabel("Postort").fill("Visby");
    await page.getByLabel("Postort").click();
    await expect(page.getByLabel("Postnummer")).toHaveValue("623 55");
    // Scoped to the Kontakt card — every card has its own "Spara".
    await page
      .locator("section", {
        has: page.getByRole("heading", {
          name: "Kontaktuppgifter",
          exact: true,
        }),
      })
      .getByRole("button", { name: "Spara", exact: true })
      .click();
    await expect(page.getByText("Kontaktuppgifter sparade")).toBeVisible();
    await page.reload();
    await expect(page.getByLabel("Gatuadress")).toHaveValue(
      `Testgatan ${stamp}`,
    );
    await expect(page.getByLabel("Postnummer")).toHaveValue("623 55");
  });

  test("has no horizontal scroll at 375px", async ({ page, context }) => {
    await loginInline(page, context, MEMBER);
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/stamboken/profil");
    await expect(
      page.getByRole("heading", { name: "Personer i medlemskapet" }),
    ).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("shows the no-member-record state for an account without a person row", async ({
    page,
    context,
  }) => {
    await loginInline(page, context, ADMIN);
    await page.goto("/stamboken/profil");
    await expect(page.getByRole("heading", { name: "Konto" })).toBeVisible();
    await expect(
      page.getByText("Du har ingen medlemspost kopplad till ditt konto."),
    ).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Kontaktuppgifter" }),
    ).toHaveCount(0);
  });

  test("familjemedlem sees the huvudmedlem name and read-only cards", async ({
    page,
    context,
  }) => {
    await loginInline(page, context, FAMILY);
    await page.goto("/stamboken/profil");
    await expect(page.getByText("Playwright TestMember")).toBeVisible();
    await expect(
      page
        .getByText("Endast huvudmedlemmen kan ändra medlemskapets uppgifter.")
        .first(),
    ).toBeVisible();
    await expect(page.getByLabel("Gatuadress")).toBeDisabled();
    await expect(
      page.getByText("Kontakta huvudmedlemmen för ändringar av medlemskapet."),
    ).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Lägg till person" }),
    ).toHaveCount(0);
  });

  test("/medlem root no longer redirects", async ({ page, context }) => {
    await loginInline(page, context, MEMBER);
    const res = await page.goto("/medlem");
    expect(res?.status()).toBe(404);
  });
});
