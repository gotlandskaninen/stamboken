import fs from "node:fs";
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";
import { psql } from "./helpers/db";

test.describe("medlem pages on the design system", () => {
  test.beforeEach(async ({ page, context }) => {
    await loginAs(page, context, ADMIN, "prod");
  });

  // local-production seeds exactly ONE membership, so ?per_page=1 renders
  // "Sida 1 av 1" and Nästa is the disabled <span> — the link the pagination
  // test clicks exists only with a second row. Seeded here rather than at file
  // level so the other three tests keep reading the untouched fixture.
  test.describe("with a throwaway second membership", () => {
    // Keyed on member_number 99920, which nothing else in the suite uses.
    const dropFixture = () => {
      // Children before the parent — the order 19-medlem-koppling.spec.ts
      // uses. The fixture owns no persons, herds or audit rows of its own,
      // but a leftover from a crashed run is torn down the same way.
      const ids =
        "SELECT membership_id FROM membership WHERE member_number = 99920";
      psql(`DELETE FROM matrikel_audit WHERE membership_id IN (${ids});`);
      psql(`DELETE FROM member WHERE membership_id IN (${ids});`);
      psql("DELETE FROM membership WHERE member_number = 99920;");
    };

    test.beforeAll(() => {
      dropFixture(); // self-heal after a crashed run
      psql(
        "INSERT INTO membership (member_number, membership_status, publication_consent, joined_date, created_at, updated_at) " +
          "VALUES (99920, 'active', '{}', CURRENT_DATE, NOW(), NOW());",
      );
    });

    test.afterAll(dropFixture);

    test("matrikel list paginates through the URL and clamps out-of-range pages", async ({
      page,
    }) => {
      await page.goto("/medlem/matrikel?per_page=1");
      await expect(
        page.getByRole("heading", { name: "Medlemsmatrikel" }),
      ).toBeVisible();
      await expect(page.getByText(/Sida 1 av \d+/)).toBeVisible();
      await page.getByRole("link", { name: "Nästa" }).click();
      await expect(page).toHaveURL(/page=2/);
      await page.goto("/medlem/matrikel?per_page=1&page=99999");
      await expect(page).not.toHaveURL(/page=99999/);
      await expect(page.getByRole("grid")).toBeVisible();
    });
  });

  test("Koharen export downloads a CSV with the fixed header", async ({
    page,
  }) => {
    await page.goto("/medlem/matrikel");
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Exportera Koharen" }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe("koharen-matrikel.csv");
    const text = fs.readFileSync((await file.path()) as string, "utf8");
    expect(text.replace(/^\uFEFF/, "").split(/\r?\n/)[0]).toBe(
      "Nr,Namn,Telefon,E-post,Gatuadress,Postnummer,Postort,Samtycke",
    );
  });

  test("ansökningar and statistik render on the DS", async ({ page }) => {
    await page.goto("/medlem/ansokningar");
    await expect(
      page.getByRole("heading", { name: "Medlemsansökningar" }),
    ).toBeVisible();
    await page.goto("/medlem/statistik");
    await expect(
      page.getByRole("heading", { name: "Styrelsestatistik" }),
    ).toBeVisible();
    await expect(page.getByText("Medlemskap totalt")).toBeVisible();
    await expect(
      page.getByRole("button", { name: "Exportera MATR" }),
    ).toBeVisible();
  });

  test("no horizontal scroll on the matrikel pages at 375px", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    for (const path of ["/medlem/matrikel", "/medlem/statistik"]) {
      await page.goto(path);
      const overflow = await page.evaluate(
        () =>
          document.documentElement.scrollWidth -
          document.documentElement.clientWidth,
      );
      expect(overflow, path).toBeLessThanOrEqual(0);
    }
  });
});
