import { test, expect, type Page } from "@playwright/test";

// Manualens "Lägga till en kanin utan registrerad kull" (docs/USER_MANUAL.md, del 1)
// mot den seedade e2e-stacken. Filnamnet matchar inget mutation-/public-mönster, så
// specen körs i projektet owner-tests (test-gk-owner, äger G1274).
// Föräldrarna Visby Vera × Visby Test-04 används inte av någon annan spec. G1274:s
// senaste seedade kull 2024 är född 2024-10-15, så en kull 2024-12-01 numreras sist
// (kullnumren följer födelsedatum). En ny körning mot samma seed hittar kullen från
// första körningen och lägger nästa kanin i den: nio körningar, sedan färsk seed.
test.setTimeout(120000);

const KANINER = "/stamboken/min-besattning?tab=individuals";
const MOTHER = { name: "Visby Vera", number: "G1274-2113" };
const FATHER = { name: "Visby Test-04", number: "G1274-2353" };
const BIRTH_DATE = "2024-12-01";

/** Dev-servern kan fastna i "Laddar…" vid första anropet; ladda om i så fall. */
async function gotoKaniner(page: Page) {
  await expect(async () => {
    await page.goto(KANINER, { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Laddar…")).toBeHidden({ timeout: 20000 });
  }).toPass({ timeout: 90000 });
}

async function pickParent(
  page: Page,
  label: RegExp,
  parent: { name: string; number: string },
) {
  const input = page.getByRole("combobox", { name: label });
  await input.click();
  await input.fill(parent.name);
  await page
    .getByRole("option")
    .filter({ hasText: parent.name })
    .filter({ hasText: parent.number })
    .click();
}

async function typeDate(page: Page, label: RegExp, isoDate: string) {
  const group = page.getByRole("group", { name: label });
  await group.locator('[data-sectionindex="0"]').click();
  await group.pressSequentially(isoDate.replace(/-/g, ""));
  await group.press("Tab");
}

test("Lägga till en kanin utan registrerad kull", async ({ page }) => {
  const dialog = page.getByRole("dialog", {
    name: /Lägg till kanin|Registrera kanin/,
  });
  let number = "";
  let suggested = "";
  await test.step('1. Öppna Min besättning, fliken "Kaniner"', async () => {
    await gotoKaniner(page);
  });
  await test.step('2. Klicka "+ Lägg till kanin"', async () => {
    await page
      .getByRole("button", { name: "+ Lägg till kanin" })
      .click({ timeout: 60000 });
    await expect(dialog).toBeVisible();
  });
  await test.step("3. Välj Mor och Far, fyll i kullen", async () => {
    await pickParent(page, /^Mor/, MOTHER);
    await pickParent(page, /^Far/, FATHER);
    await typeDate(page, /Födelsedatum/, BIRTH_DATE);
    await dialog.getByLabel(/Antal födda/).fill("9");
    await dialog.getByLabel(/Levande i kullen efter 6 veckor/).fill("9");
    // The number suggestion follows the litter: herd, year 24, then litter and place
    await expect(
      page.getByRole("dialog", { name: /Registrera kanin — G1274-24/ }),
    ).toBeVisible({ timeout: 15000 });
    suggested =
      (await page.locator("#register-rabbit-title").textContent())?.match(
        /G1274-\d+/,
      )?.[0] ?? "";
  });
  await test.step("4. Välj Kön och Färg", async () => {
    // Kön- och Intyg-listorna saknar tillgängligt namn (MUI Select utan labelId):
    // Kön är första listan, Intyg den som visar "Digitalt" (förvalt här).
    await dialog.getByRole("combobox").filter({ hasText: "Hona" }).click();
    await page.getByRole("option", { name: "Hona" }).click();
    await dialog.getByRole("textbox", { name: /^Färg/ }).first().fill("Blå");
  });
  await test.step('5. Välj Intyg "Papper", skriv Intygsnummer och Individnummer på pappret', async () => {
    await dialog.getByRole("combobox").filter({ hasText: "Digitalt" }).click();
    await page.getByRole("option", { name: "Papper" }).click();
    await dialog
      .getByRole("textbox", { name: /^Intygsnummer/ })
      .fill(`E2E-${Date.now() % 1e10}`);
    // A paper that agrees with Stamboken: no number conflict
    await dialog.getByLabel(/Individnummer på pappret/).fill(suggested);
  });
  await test.step('6. Klicka "Registrera"', async () => {
    await dialog
      .getByRole("button", { name: "Registrera", exact: true })
      .click();
    const success = dialog.getByText(/registrerad som G1274-24\d+/);
    await expect(success).toBeVisible({ timeout: 30000 });
    number = (await success.textContent())?.match(/G1274-\d+/)?.[0] ?? "";
    expect(number).not.toBe("");
    await dialog.getByRole("button", { name: "Avbryt" }).click();
    await expect(dialog).toBeHidden();
  });
  await test.step("7. Kaninen finns i listan", async () => {
    await page.getByRole("button", { name: /^Alla \(/ }).click();
    await page.getByLabel("Sök nummer eller namn").fill(number);
    await expect(page.getByText(number, { exact: true })).toBeVisible({
      timeout: 15000,
    });
  });
});
