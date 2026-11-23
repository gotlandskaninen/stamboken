import { test, expect, type Page } from "@playwright/test";
import { loginInline, TEST_USERS } from "../e2e-shared/auth";

// Seed (create_test_users.py, #117 block, then link_herd): test-member's herd is linked to her membership,
// her name is the contact person's, its e-post is empty (fetched from her) and its own mobile differs from
// hers (pending "Stämmer det?"). The steps change that herd, so they run in order.
const PAGE = "/stamboken/min-besattning?tab=overview";
const MAIN = "Playwright TestMember";
const FAMILY = "Playwright Family";
const MAIN_MOBILE = "070-000 00 01"; // the register's, from the seed
const ASK = "Mobilnumret skiljer sig";

const card = (page: Page) =>
  page.locator("section").filter({
    has: page.getByRole("heading", {
      name: "Kontakt för besättningen",
      level: 2,
    }),
  });

// the rows list under a group heading (ContactView: <h3> then <dl>), and one row in it
const group = (page: Page, title: RegExp) =>
  card(page)
    .getByRole("heading", { name: title })
    .locator("xpath=following-sibling::dl[1]");
const row = (list: ReturnType<typeof group>, label: string) =>
  list
    .locator("div")
    .filter({ has: list.page().getByText(label, { exact: true }) });

const FETCHED = /^Från ditt medlemskap/;
const OWN = /^Egna för besättningen/;

// The steps use up the seed (the pending mobile), so a retry would start from a changed herd: no retries;
// a re-run of the job gets a fresh seed.
test.describe.configure({ mode: "serial", retries: 0 });

test.describe("Min besättning: kontakt från matrikeln", () => {
  test.beforeEach(async ({ page, context }) => {
    await loginInline(page, context, TEST_USERS.member);
  });

  test("shows the source per row and asks about the differing mobile", async ({
    page,
  }) => {
    await page.goto(PAGE);
    await expect(
      card(page).getByRole("heading", { name: FETCHED }),
    ).toBeVisible();
    await expect(
      group(page, FETCHED).getByRole("link", {
        name: "test-member@test.local",
      }),
    ).toBeVisible();
    await expect(row(group(page, OWN), "Mobil")).toBeVisible();
    const ask = card(page).getByRole("group", { name: ASK });
    await expect(ask).toBeVisible();
    await expect(
      ask.getByText("Stämmer numret för besättningen?"),
    ).toBeVisible();
  });

  test("answering 'Använd medlemskapets' fetches the register's mobile", async ({
    page,
  }) => {
    await page.goto(PAGE);
    await card(page)
      .getByRole("group", { name: ASK })
      .getByRole("button", { name: "Använd medlemskapets" })
      .click();
    await expect(
      page.getByText("Sparat: uppgiften hämtas nu från ditt medlemskap."),
    ).toBeVisible();

    // what was stored, not what the button implies
    await page.reload();
    await expect(card(page).getByRole("group", { name: ASK })).toBeHidden();
    const mobile = row(group(page, FETCHED), "Mobil");
    await expect(mobile.getByText(MAIN_MOBILE)).toBeVisible();
    await expect(mobile.getByText("Endast genbanksansvarig")).toBeVisible();
  });

  test("switching contact person to the family member shows her e-post, and back", async ({
    page,
  }) => {
    await page.goto(PAGE);
    await card(page).getByRole("button", { name: "Redigera" }).click();
    await page
      .locator("#contact-person")
      .selectOption({ label: `${FAMILY}, familjemedlem` });
    await card(page)
      .getByRole("button", { name: "Spara", exact: true })
      .click();
    await expect(
      page.getByText("Kontaktuppgifter sparade").first(),
    ).toBeVisible();
    await expect(
      card(page).getByText(FAMILY, { exact: true }).first(),
    ).toBeVisible();
    await expect(
      card(page).getByRole("link", { name: "test-family@test.local" }),
    ).toBeVisible();

    // put the person back (the herd is also reset after the group)
    await card(page).getByRole("button", { name: "Redigera" }).click();
    await page
      .locator("#contact-person")
      .selectOption({ label: `${MAIN}, huvudmedlem` });
    await card(page)
      .getByRole("button", { name: "Spara", exact: true })
      .click();
    await expect(
      card(page).getByRole("link", { name: "test-member@test.local" }),
    ).toBeVisible();
  });

  test("the name is made private in the flow", async ({ page }) => {
    // a fresh seed shows the name to logged-in herds; the owner test below needs it private
    await page.goto(PAGE);
    await card(page).getByRole("button", { name: "Redigera" }).click();
    const chip = card(page)
      .getByRole("group", { name: "Vem ser namnet" })
      .getByRole("button", { name: "Endast genbanksansvarig" });
    if ((await chip.getAttribute("aria-pressed")) !== "true") {
      await chip.click();
      await card(page)
        .getByRole("button", { name: "Spara", exact: true })
        .click();
      await expect(
        page.getByText("Kontaktuppgifter sparade").first(),
      ).toBeVisible();
    } else {
      await card(page).getByRole("button", { name: "Avbryt" }).click();
    }
    await page.reload();
    await expect(
      card(page).getByText("Endast genbanksansvarig").first(),
    ).toBeVisible();
  });

  test("has no horizontal scroll at 375px", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(PAGE);
    await expect(
      card(page).getByRole("heading", { name: FETCHED }),
    ).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});

test("legacy owner sees neither a fetched row's value nor the contact person", async ({
  page,
  context,
}) => {
  // test-gk-owner only has the old owner role on the same herd: not a register reader.
  await loginInline(page, context, TEST_USERS.owner);
  const response = await page.goto(PAGE);
  await expect(
    card(page).getByRole("heading", { name: "Kontakt för besättningen" }),
  ).toBeVisible();
  await expect(
    row(card(page).locator("dl").first(), "E-post").getByText(
      "Hämtas från medlemskapet",
    ),
  ).toBeVisible();

  // the rendered page and the document with its serialized client data
  const html = await response!.text();
  const text = await page.locator("body").innerText();
  for (const hidden of [
    MAIN,
    FAMILY,
    "test-member@test.local",
    "test-family@test.local",
    MAIN_MOBILE,
  ]) {
    expect(text).not.toContain(hidden);
    expect(html).not.toContain(hidden);
  }
});
