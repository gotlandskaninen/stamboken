import { test, expect, type Page } from "@playwright/test";

// Manualens steg som tester (docs/USER_MANUAL.md, del 1 Uppfödare). Varje
// test.step heter som steget i manualen; ändras manualen ändras testet.
// Kör i projektet mutation-tests (filnamnet matchar /mutation-.*/) mot den
// seedade e2e-stacken: G1274 ägs av test-gk-owner; föräldraparet
// Visby Saga × Visby Storm används inte av något annat mutationstest.
// Digitalt intyg kräver S3 (s3backend) i stacken.

test.describe.configure({ mode: "serial" });
test.setTimeout(120000);

const BREEDING = "/stamboken/min-besattning?tab=breeding";
const MOTHER = { name: "Visby Saga", number: "G1274-2115" };
const FATHER = { name: "Visby Storm", number: "G1274-2116" };
// Födelsedatum: den 1:a i en udda månad 2025, vald per minut. Honan får inte ha
// överlappande dräktigheter (parningsdatum = födelsedatum − 31 dagar), så
// slottarna ligger två månader isär; sex körningar i rad fungerar mot samma
// seed, därefter: stacken ned och upp igen (färsk seed). Kullen måste vara
// äldre än 6 veckor för att ungar ska gå att registrera.
// Vid retry (serial: hela filen körs om) flyttas slotten ett steg.
let BIRTH_DATE = "";
function pickBirthDate(retry: number) {
  const minutes = Math.floor(Date.now() / 60000);
  const birthMonth = String(((minutes + retry) % 6) * 2 + 1).padStart(2, "0");
  BIRTH_DATE = `2025-${birthMonth}-01`;
}

/** Dev-servern kan fastna i "Laddar…" vid första anropet; ladda om i så fall. */
async function gotoBreeding(page: Page) {
  await expect(async () => {
    await page.goto(BREEDING, { waitUntil: "domcontentloaded" });
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

/** "Kullnumren stämmer inte" kan dyka upp när kullar inte registrerats i datumordning. */
async function renumberIfAsked(page: Page) {
  const dialog = page.getByRole("dialog", { name: "Kullnumren stämmer inte" });
  if (await dialog.isVisible({ timeout: 3000 }).catch(() => false)) {
    await dialog
      .getByRole("button", { name: "Numrera om kullar automatiskt" })
      .click();
    await expect(dialog).toBeHidden({ timeout: 15000 });
  }
}

test("Registrera kull", async ({ page }) => {
  pickBirthDate(test.info().retry);
  await test.step('1. Öppna Min besättning, fliken "Kullar och parningar"', async () => {
    await gotoBreeding(page);
  });
  await test.step('2. Klicka "+ Ny kull"', async () => {
    await page
      .getByRole("button", { name: /\+ Ny kull/ })
      .click({ timeout: 60000 });
  });
  await test.step("3. Välj Mor och Far", async () => {
    await pickParent(page, /^Mor/, MOTHER);
    await pickParent(page, /^Far/, FATHER);
  });
  await test.step("4. Fyll i Födelsedatum, Antal födda och Antal vid 6 veckor", async () => {
    await typeDate(page, /Födelsedatum/, BIRTH_DATE);
    await page.getByLabel(/Antal födda/).fill("5");
    await page.getByLabel(/Antal vid 6 veckor/).fill("5");
  });
  await test.step('5. Klicka "Registrera kull"', async () => {
    await page.getByRole("button", { name: "Registrera kull" }).click();
    await expect(page.getByText("Kull registrerad!")).toBeVisible({
      timeout: 15000,
    });
  });
});

test("Registrera unge och utfärda digitalt intyg", async ({ page }) => {
  let certificateUrl = "";
  await test.step('1. Öppna kullens kort med "Detaljer"', async () => {
    await gotoBreeding(page);
    const card = page
      .locator('[data-testid="breeding-card"]')
      .filter({ hasText: MOTHER.name })
      .filter({ hasText: `Född ${BIRTH_DATE}` })
      .first();
    await expect(card).toBeVisible({ timeout: 60000 });
    await card.getByRole("button", { name: "Detaljer" }).click();
    await expect(
      card.getByText("6 veckor passerade — kan registreras"),
    ).toBeVisible();
  });
  await test.step("2. Kullistan har redan en rad per född unge", async () => {
    await expect(page.getByText("Kullista (5 av 5)")).toBeVisible({
      timeout: 15000,
    });
  });
  await test.step('3. Klicka "Registrera" på ungens rad', async () => {
    await page
      .getByRole("button", { name: "Registrera", exact: true })
      .first()
      .click();
    await renumberIfAsked(page);
    await expect(
      page.getByRole("dialog", { name: /Registrera kanin/ }),
    ).toBeVisible({ timeout: 15000 });
  });
  const dialog = page.getByRole("dialog", { name: /Registrera kanin/ });
  await test.step("4. Välj Kön och Färg", async () => {
    // Kön- och Intyg-listorna saknar tillgängligt namn (MUI Select utan labelId):
    // Kön är första listan i dialogen, Intyg den som visar "Digitalt" (förvalt;
    // intyg krävs för registrering).
    await dialog.getByRole("combobox").first().click();
    await page.getByRole("option", { name: "Hona" }).click();
    const color = dialog.getByRole("combobox", { name: "Färg" });
    await color.click();
    await color.fill("Blå");
    await page.getByRole("option", { name: "Blå", exact: true }).click();
  });
  await test.step('5. Välj Intyg: "Digitalt"', async () => {
    await dialog.getByRole("combobox").filter({ hasText: "Digitalt" }).click();
    await page.getByRole("option", { name: "Digitalt" }).click();
  });
  await test.step('6. Klicka "Registrera"', async () => {
    await dialog
      .getByRole("button", { name: "Registrera", exact: true })
      .click();
    await renumberIfAsked(page);
    await expect(dialog.getByText(/registrerad som G1274-/)).toBeVisible({
      timeout: 30000,
    });
    await expect(dialog.getByText("Intyget kunde inte skapas")).toHaveCount(0);
    const link = dialog.getByRole("link", { name: "Visa intyg" });
    await expect(link).toBeVisible();
    certificateUrl = (await link.getAttribute("href")) ?? "";
  });
  await test.step('7. "Visa intyg" ger en signerad PDF', async () => {
    const res = await page.request.get(certificateUrl);
    expect(res.status()).toBe(200);
    expect(res.headers()["content-type"]).toContain("application/pdf");
  });
});

test("Sälja kanin (och ångra)", async ({ page }) => {
  // Självläkande: om en tidigare körning avbröts efter flytten ångras den först.
  const INDIVIDUAL = "/stamboken/individ/G1274-2464";
  const undoSale = async () => {
    const dialog = page.getByRole("dialog", { name: "Ångra försäljning" });
    await dialog.getByLabel("Anledning").fill("Test av manualen");
    await dialog.getByRole("button", { name: "Ångra försäljning" }).click();
    await expect(page.getByText("Försäljningen är ångrad.")).toBeVisible({
      timeout: 15000,
    });
  };
  await test.step("1. Öppna kaninens sida", async () => {
    await page.goto(INDIVIDUAL, { waitUntil: "domcontentloaded" });
    await expect(
      page.getByRole("heading", { name: "Visby Test-15" }),
    ).toBeVisible({ timeout: 60000 });
    await page.getByRole("button", { name: "Fler åtgärder" }).click();
    const undo = page.getByRole("menuitem", { name: "Ångra försäljning" });
    if (await undo.isVisible().catch(() => false)) {
      await undo.click();
      await undoSale();
      await page.goto(INDIVIDUAL, { waitUntil: "domcontentloaded" });
    } else {
      await page.keyboard.press("Escape");
    }
  });
  await test.step('2. Öppna "Fler åtgärder" och välj "Sälj individ"', async () => {
    // Direkt efter en ångrad försäljning kan sidan en kort stund visa den gamla
    // behörigheten (menyvalet grått); ladda om tills det går att välja.
    await expect(async () => {
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.getByRole("button", { name: "Fler åtgärder" }).click();
      await expect(
        page.getByRole("menuitem", { name: "Sälj individ" }),
      ).toBeEnabled({ timeout: 3000 });
    }).toPass({ timeout: 30000 });
    await page.getByRole("menuitem", { name: "Sälj individ" }).click();
    await expect(
      page.getByRole("dialog", { name: /byter hem|^Sälj / }),
    ).toBeVisible();
  });
  // Säljdialogens texter byts i chore/ui-terms; regexen täcker gamla och nya.
  const dialog = page.getByRole("dialog", { name: /byter hem|^Sälj / });
  await test.step('3. Välj "Ny besättning"', async () => {
    const herd = dialog.getByRole("combobox", { name: "Ny besättning" });
    await herd.click();
    await herd.fill("G1398");
    await page.getByRole("option", { name: /G1398/ }).click();
  });
  await test.step("4. Kontrollera Säljdatum (förifyllt med dagens datum)", async () => {
    await expect(
      dialog.getByRole("group", { name: /Säljdatum/ }),
    ).toBeVisible();
  });
  await test.step('5. Kryssa i bekräftelsen och klicka "Bekräfta försäljning"', async () => {
    await dialog.getByRole("checkbox").check();
    await dialog
      .getByRole("button", { name: /Bekräfta (flytt|försäljning)/ })
      .click();
    await expect(
      page.getByText(/(har flyttats|är såld) till G1398/).first(),
    ).toBeVisible({ timeout: 15000 });
  });
  await test.step('6. Ångra med "Ångra försäljning" (inom 7 dagar)', async () => {
    await page
      .getByRole("button", { name: "Ångra försäljning" })
      .first()
      .click();
    await undoSale();
  });
});
