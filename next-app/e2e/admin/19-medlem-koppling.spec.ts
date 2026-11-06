import { test, expect } from "@playwright/test";
import { loginAs, ADMIN, VICTIM_ROLE } from "./helpers/auth";
import { psql } from "./helpers/db";

// Seeds a membership owning a fresh GK herd so linking test-mk-owner to its
// huvudmedlem conveys access it does not have → confirm-with-warning path.
let membershipId = "";
let mainId = "";
let familyId = "";

test.beforeAll(() => {
  // Self-heal after a crashed run: drop any leftover fixture in the same order
  // afterAll uses (children before parents) before re-seeding.
  const stale = psql(
    "SELECT membership_id FROM membership WHERE member_number = 99919;",
  );
  if (stale) {
    psql(`DELETE FROM matrikel_audit WHERE membership_id = ${stale};`);
    psql(
      `DELETE FROM herd_access_grant WHERE member_id IN (SELECT member_id FROM member WHERE membership_id = ${stale});`,
    );
    psql(`DELETE FROM member WHERE membership_id = ${stale};`);
  }
  // Unconditional: a crash between the two INSERTs can leave G9919 behind
  // with no membership row to find it from.
  psql("DELETE FROM herd WHERE herd = 'G9919';");
  if (stale) {
    psql(`DELETE FROM membership WHERE membership_id = ${stale};`);
  }
  membershipId = psql(
    "INSERT INTO membership (member_number, membership_status, publication_consent, joined_date, created_at, updated_at) " +
      "VALUES (99919, 'active', '{}', CURRENT_DATE, NOW(), NOW()) RETURNING membership_id;",
  );
  psql(
    "INSERT INTO herd (genebank_id, herd, herd_name, is_active, membership_id) " +
      `VALUES ((SELECT genebank_id FROM genebank WHERE name = 'Gotlandskanin'), 'G9919', 'E2E koppling', true, ${membershipId});`,
  );
  mainId = psql(
    `INSERT INTO member (membership_id, first_name, last_name, role, created_at, updated_at) VALUES (${membershipId}, 'E2E', 'Huvud', 'huvudmedlem', NOW(), NOW()) RETURNING member_id;`,
  );
  familyId = psql(
    `INSERT INTO member (membership_id, first_name, last_name, role, created_at, updated_at) VALUES (${membershipId}, 'E2E', 'Familj', 'familjemedlem', NOW(), NOW()) RETURNING member_id;`,
  );
});

test.afterAll(() => {
  psql(`DELETE FROM matrikel_audit WHERE membership_id = ${membershipId};`);
  psql(
    `DELETE FROM herd_access_grant WHERE member_id IN (${mainId}, ${familyId});`,
  );
  psql(`DELETE FROM member WHERE membership_id = ${membershipId};`);
  psql("DELETE FROM herd WHERE herd = 'G9919';");
  psql(`DELETE FROM membership WHERE membership_id = ${membershipId};`);
});

test.describe("kontokoppling on matrikel-detaljen", () => {
  test.beforeEach(async ({ page, context }) => {
    await loginAs(page, context, ADMIN, "prod");
    await page.goto(`/medlem/matrikel/${membershipId}`);
  });

  test("search → select → warning → confirm → Konto column → unlink", async ({
    page,
  }) => {
    const mainRow = page.getByRole("row", { name: /E2E Huvud/ });
    await mainRow.getByRole("button", { name: "Koppla konto…" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Sök användare").fill(VICTIM_ROLE.username);
    await dialog
      .getByRole("option", { name: new RegExp(VICTIM_ROLE.username) })
      .click();
    await dialog.getByRole("button", { name: "Koppla konto" }).click();
    await expect(dialog.getByRole("status")).toContainText(
      "Kontot får ägaråtkomst till G9919 — E2E koppling.",
    );
    await dialog.getByRole("button", { name: "Koppla konto" }).click();
    await expect(page.getByText("Konto kopplat")).toBeVisible();
    await expect(mainRow.getByText(VICTIM_ROLE.username)).toBeVisible();
    await expect(page.getByText("Kopplade konton")).toBeVisible();
    await expect(page.getByText("1 av 2 personer")).toBeVisible();

    await mainRow.getByRole("button", { name: "Koppla bort" }).click();
    await expect(page.getByRole("dialog")).toContainText(
      "Kontot förlorar åtkomsten som medlemskapet ger. Fortsätt?",
    );
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Bekräfta" })
      .click();
    await expect(page.getByText("Konto bortkopplat")).toBeVisible();
    await expect(
      mainRow.getByRole("button", { name: "Koppla konto…" }),
    ).toBeVisible();
  });

  test("an ended linked person still offers Koppla bort and the account can be relinked elsewhere", async ({
    page,
  }) => {
    const familyRow = page.getByRole("row", { name: /E2E Familj/ });
    await familyRow.getByRole("button", { name: "Koppla konto…" }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Sök användare").fill(VICTIM_ROLE.username);
    await dialog
      .getByRole("option", { name: new RegExp(VICTIM_ROLE.username) })
      .click();
    await dialog.getByRole("button", { name: "Koppla konto" }).click(); // familjemedlem without grants: no warning
    await expect(page.getByText("Konto kopplat")).toBeVisible();

    await familyRow.getByRole("button", { name: /Fler åtgärder/ }).click();
    await page.getByRole("menuitem", { name: "Ta bort" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Bekräfta" })
      .click();
    await expect(page.getByText("Person borttagen")).toBeVisible();
    await expect(
      familyRow.getByRole("button", { name: "Koppla bort" }),
    ).toBeVisible();
    await expect(
      familyRow.getByRole("button", { name: "Koppla konto…" }),
    ).toHaveCount(0);

    await familyRow.getByRole("button", { name: "Koppla bort" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Bekräfta" })
      .click();
    await expect(page.getByText("Konto bortkopplat")).toBeVisible();

    const mainRow = page.getByRole("row", { name: /E2E Huvud/ });
    await mainRow.getByRole("button", { name: "Koppla konto…" }).click();
    await page
      .getByRole("dialog")
      .getByLabel("Sök användare")
      .fill(VICTIM_ROLE.username);
    await page
      .getByRole("dialog")
      .getByRole("option", { name: new RegExp(VICTIM_ROLE.username) })
      .click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Koppla konto" })
      .click();
    await expect(page.getByRole("dialog").getByRole("status")).toContainText(
      "Kontot får ägaråtkomst till G9919 — E2E koppling.",
    );
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Koppla konto" })
      .click(); // confirm the warning
    await expect(page.getByText("Konto kopplat")).toBeVisible();
    await mainRow.getByRole("button", { name: "Koppla bort" }).click();
    await page
      .getByRole("dialog")
      .getByRole("button", { name: "Bekräfta" })
      .click();
    // Wait for the unlink to land before afterAll tears the fixture down —
    // otherwise its matrikel_audit row is written between the audit and
    // membership DELETEs and the FK on matrikel_audit fails the teardown.
    await expect(
      mainRow.getByRole("button", { name: "Koppla konto…" }),
    ).toBeVisible();
  });
});
