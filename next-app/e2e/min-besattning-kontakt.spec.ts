import { test, expect, type Page } from "@playwright/test";
import { loginInline, TEST_USERS } from "../e2e-shared/auth";
import { psql } from "./admin/helpers/db";

// Seed (create_test_users.py, #117 block, then link_herd): test-member's herd is linked to her membership,
// her name is the contact person's, its e-post is empty (fetched from her) and its own mobile differs from
// hers (pending "Stämmer det?"). The steps change that herd, so they run in order, and the herd is put back
// before the group (also on a retry) and after it.
const PAGE = "/stamboken/min-besattning?tab=overview";
const MAIN = "Playwright TestMember";
const FAMILY = "Playwright Family";
const MAIN_MOBILE = "070-000 00 01"; // the register's, from the seed
const ASK = "Mobilnumret skiljer sig";

function resetHerd() {
  // ids are looked up by username; one row must change, or the seed is not what the spec assumes
  const changed = psql(`
    UPDATE herd h SET contact_member_id = m.member_id, name = NULL, email = NULL, email_privacy = 'private',
      mobile_phone = '070-000 00 02', contact_pending = '["mobile_phone"]'::jsonb
    FROM member m JOIN hbuser u ON u.user_id = m.user_id
    WHERE u.username = '${TEST_USERS.member.username}' AND m.role = 'huvudmedlem' AND m.end_date IS NULL
      AND h.membership_id = m.membership_id
    RETURNING h.herd_id;`);
  expect(changed).toMatch(/^\d+(\n\d+)*$/);
  expect(changed.split("\n")).toHaveLength(1);
}

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

test.describe.configure({ mode: "serial" });
test.beforeAll(resetHerd);
test.afterAll(resetHerd);

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

  test("has no horizontal scroll at 375px", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(PAGE);
    await expect(card(page).getByRole("group", { name: ASK })).toBeVisible();
    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
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
