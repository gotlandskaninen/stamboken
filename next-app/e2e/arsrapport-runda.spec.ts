import { expect, test, type Page } from "@playwright/test";
import { loginInline } from "../e2e-shared/auth";

// A full yearly report round for 2025 on the data of `flask seed arsrapport` (synthetic herds G9001-G9004),
// at 375 px: the manager activates the round, the owner reports G9001 and G9004 (183 rabbits through the Next
// actions), a genebank helper enters G9002's paper form, and the manager reads the status.
//
// The steps change shared state and depend on each other, so the file runs serially and never retries: a retry
// after a half-done run could only fail for a different reason. It assumes a freshly seeded database, as CI's
// is. To run it again locally, `docker compose down -v` and seed again.
test.describe.configure({ mode: "serial", retries: 0 });
test.use({ viewport: { width: 375, height: 812 }, hasTouch: true });
test.setTimeout(120_000);

const USERS = {
  manager: { username: "seed-gk-mgr@test.local", password: "seed-gk-pass" },
  owner: {
    username: "seed-gk-arsrapport@test.local",
    password: "seed-gk-arsrapport-pass",
  },
  helper: {
    username: "seed-gk-hjalp@test.local",
    password: "seed-gk-hjalp-pass",
  },
};
// SUBMIT_TIMEOUT_MS in arsrapport/lib.ts: Skicka answers within it, also for 183 rabbits.
const SUBMIT_TIMEOUT_MS = 30_000;
const NO_DISEASE = "Inga sjukdomsfall eller defekter";

const rows = (page: Page) => page.locator('fieldset[id^="rabbit-"]');
const row = (page: Page, herd: string) =>
  page.getByRole("row").filter({ hasText: herd });

test("1. Genbanksansvarig aktiverar rundan för Gotlandskanin", async ({
  page,
  context,
}) => {
  await loginInline(page, context, USERS.manager);
  await page.goto("/stamboken/arsrapport");
  await page
    .getByRole("link", { name: /Status för genbanken, runda 2025/ })
    .click();
  await expect(
    page.getByRole("heading", {
      name: "Rundan 2025 är inte aktiverad för Gotlandskanin",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Aktivera", exact: true }).click();
  await expect(page.getByText(/^Aktiverad /)).toBeVisible();
});

test("2. Uppfödaren skickar G9001 och G9004", async ({ page, context }) => {
  await loginInline(page, context, USERS.owner);

  // G9001: 13 rows, 12 to choose (one rabbit moved in January and counts through the move).
  await page.goto("/stamboken/arsrapport/G9001/2025");
  const all = rows(page);
  await expect(all).toHaveCount(13);
  const choosable: number[] = [];
  for (let i = 0; i < (await all.count()); i++)
    if (await all.nth(i).getByRole("radio", { name: "Finns kvar" }).count())
      choosable.push(i);
  expect(choosable).toHaveLength(12);
  const dead = choosable.pop()!;
  for (const i of choosable) {
    const r = all.nth(i);
    await r.getByRole("radio", { name: "Finns kvar" }).check();
    await r.getByLabel("Vikt", { exact: true }).fill("2,8");
  }
  const died = all.nth(dead);
  await died.getByRole("radio", { name: "Död eller slaktad" }).check();
  await died.locator('select[id^="month-"]').selectOption("10");
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await page.getByRole("button", { name: "Skicka årsrapporten" }).click();
  await expect(page.getByText(/^Inskickad /)).toBeVisible({
    timeout: SUBMIT_TIMEOUT_MS,
  });

  // G9004: 183 rabbits born in 2025, none needs a weight. "Markera resten" opens after the last row was seen.
  await page.goto("/stamboken/arsrapport/G9004/2025");
  await expect(rows(page)).toHaveCount(183);
  await rows(page).last().scrollIntoViewIfNeeded();
  await page
    .getByRole("button", { name: "Markera resten som finns kvar" })
    .click();
  await page
    .getByRole("alertdialog", { name: "Markera resten" })
    .getByRole("button", { name: "Ja, markera" })
    .click();
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await page.getByRole("button", { name: "Skicka årsrapporten" }).click();
  await expect(page.getByText(/^Inskickad /)).toBeVisible({
    timeout: SUBMIT_TIMEOUT_MS,
  });
});

test("3. Hjälparen matar in G9002:s blankett", async ({ page, context }) => {
  await loginInline(page, context, USERS.helper);
  await page.goto("/stamboken/inkorg");
  await row(page, "G9002").getByRole("button", { name: "Jag tar den" }).click();
  await page.getByRole("link", { name: "Mata in årsrapporten" }).click();
  await page.waitForURL(/\/stamboken\/arsrapport\/G9002\/2025\?post=\d+/);

  // Nine of the twelve rabbits are on the form (G9002-2413 to 2421); the first two and the male are not.
  const entered = rows(page);
  for (let k = 0; k < 9; k++) {
    const number = page.getByLabel("Nummer efter G9002-");
    await number.fill(String(2413 + k));
    await number.press("Enter");
    const r = entered.nth(k);
    await r.getByRole("radio", { name: "Finns kvar" }).check();
    await r.getByLabel("Vikt", { exact: true }).fill("2,6");
  }
  await page
    .getByRole("button", { name: "Markera som ej angivna på blanketten" })
    .click();

  // The account shows only its last two digits; a new one and a new phone number are typed.
  await expect(page.getByText("Nuvarande konto slutar på ••12")).toBeVisible();
  await expect(page.locator("body")).not.toContainText("123456712");
  await page.getByLabel("Clearingnummer").fill("8327");
  await page.getByLabel("Kontonummer").fill("9123456734");
  await page.getByLabel("Bank", { exact: true }).fill("Testbanken");
  await page.getByLabel("Telefon", { exact: true }).fill("0701234567");
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await page.getByRole("button", { name: "Skicka och nästa blankett" }).click();

  await expect(page.getByText(/^Inskickad /)).toBeVisible({
    timeout: SUBMIT_TIMEOUT_MS,
  });
  await expect(page.getByText(/Sparat i matrikeln: .*konto/)).toBeVisible();
});

test("4. Genbanksansvarig ser alla tre som inskickade", async ({
  page,
  context,
}) => {
  await loginInline(page, context, USERS.manager);
  await page.goto("/stamboken/arsrapport/status/2025");
  for (const herd of ["G9001", "G9004"]) {
    const r = row(page, herd);
    await expect(r).toContainText("Inskickad");
    await expect(r).toContainText("inloggad");
  }
  const paper = row(page, "G9002");
  await expect(paper).toContainText("Inskickad");
  await expect(paper).toContainText(/Inskickad\s*blankett/);
  await expect(paper).toContainText("3 ej angivna (påverkar stödet)");
  await expect(row(page, "G9003")).toContainText("Ingen e-post");
});
