import { test, expect } from "@playwright/test";
import { loginInline, TEST_USERS } from "../e2e-shared/auth";

// Seed (create_test_users.py, #117 block): test-member's herd is linked to her membership. Its name is hers,
// its e-post is empty (fetched from her) and its own mobile differs from hers (pending "Stämmer det?").
// The steps change that herd, so they run in order and the last one puts the contact person back.
const PAGE = "/stamboken/min-besattning?tab=overview";
const MAIN = "Playwright TestMember";
const FAMILY = "Playwright Family";

test.describe.configure({ mode: "serial" });

test.describe("Min besättning: kontakt från matrikeln", () => {
  test.beforeEach(async ({ page, context }) => {
    await loginInline(page, context, TEST_USERS.member);
  });

  test("shows the source per row and asks about the differing mobile", async ({
    page,
  }) => {
    await page.goto(PAGE);
    await expect(page.getByText("Kontakt för besättningen")).toBeVisible();
    await expect(page.getByText("Från ditt medlemskap")).toBeVisible();
    await expect(
      page.getByRole("link", { name: "test-member@test.local" }),
    ).toBeVisible();
    const ask = page.getByRole("group", {
      name: "Mobilnumret skiljer sig",
    });
    await expect(ask).toBeVisible();
    await expect(
      ask.getByText("Stämmer numret för besättningen?"),
    ).toBeVisible();
    await expect(page.getByText("Egna för besättningen")).toBeVisible();
  });

  test("has no horizontal scroll at 375px", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(PAGE);
    await expect(
      page.getByRole("group", { name: "Mobilnumret skiljer sig" }),
    ).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("answering 'Använd medlemskapets' fetches the mobile", async ({
    page,
  }) => {
    await page.goto(PAGE);
    await page
      .getByRole("group", { name: "Mobilnumret skiljer sig" })
      .getByRole("button", { name: "Använd medlemskapets" })
      .click();
    await expect(
      page.getByText("Sparat: uppgiften hämtas nu från ditt medlemskap."),
    ).toBeVisible();
    await expect(
      page.getByRole("group", { name: "Mobilnumret skiljer sig" }),
    ).toBeHidden();
  });

  test("switching contact person to the family member shows her e-post, and back", async ({
    page,
  }) => {
    await page.goto(PAGE);
    await page.getByRole("button", { name: "Redigera" }).click();
    await page
      .locator("#contact-person")
      .selectOption({ label: `${FAMILY}, familjemedlem` });
    await page.getByRole("button", { name: "Spara", exact: true }).click();
    await expect(
      page.getByText("Kontaktuppgifter sparade").first(),
    ).toBeVisible();
    await expect(page.getByText(FAMILY, { exact: true }).first()).toBeVisible();
    await expect(
      page.getByRole("link", { name: "test-family@test.local" }),
    ).toBeVisible();

    // put the herd back for the specs that run next to this one
    await page.getByRole("button", { name: "Redigera" }).click();
    await page
      .locator("#contact-person")
      .selectOption({ label: `${MAIN}, huvudmedlem` });
    await page.getByRole("button", { name: "Spara", exact: true }).click();
    await expect(
      page.getByRole("link", { name: "test-member@test.local" }),
    ).toBeVisible();
  });
});

test("legacy owner sees neither a fetched row's value nor the contact person", async ({
  page,
  context,
}) => {
  // test-gk-owner only has the old owner role on the same herd: not a register reader.
  await loginInline(page, context, TEST_USERS.owner);
  await page.goto(PAGE);
  await expect(page.getByText("Kontakt för besättningen")).toBeVisible();
  await expect(
    page.getByText("Hämtas från medlemskapet").first(),
  ).toBeVisible();
  const text = await page.locator("body").innerText();
  for (const hidden of [
    MAIN,
    FAMILY,
    "test-member@test.local",
    "test-family@test.local",
  ]) {
    expect(text).not.toContain(hidden);
  }
});
