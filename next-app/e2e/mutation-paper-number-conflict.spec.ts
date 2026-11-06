import { test, expect, type Page } from "@playwright/test";

// Pappersintygets individnummer mot Stambokens (spec 2026-10-30), mot den seedade
// e2e-stacken som gk-owner (äger G1274). Lägg till kanin med Papper och en
// kullsiffra som pappret har fel: konfliktrutan visas och inget sparas förrän
// uppfödaren väljer. Föräldrarna Visby Vilda × Visby Test-04 används inte av
// någon annan spec; födelsedatumet 2024-12-01 är detsamma som
// mutation-add-rabbit-shortcut, så ingen av kullarna föds före den andra.
// En ny körning hittar kullen från första körningen: pappret har ändå fel
// kullsiffra, så samma flöde gäller. Inte körd i CI-lokalt (--quick).
test.setTimeout(120000);

const KANINER = "/stamboken/min-besattning?tab=individuals";
const BIRTH_DATE = "2024-12-01";

async function gotoKaniner(page: Page) {
  await expect(async () => {
    await page.goto(KANINER, { waitUntil: "domcontentloaded" });
    await expect(page.getByText("Laddar…")).toBeHidden({ timeout: 20000 });
  }).toPass({ timeout: 90000 });
}

async function pickParent(page: Page, label: RegExp, name: string) {
  const input = page.getByRole("combobox", { name: label });
  await input.click();
  await input.fill(name);
  await page.getByRole("option").filter({ hasText: name }).first().click();
}

/** Fills Lägg till kanin with a paper whose litter digit is one too high; returns Stamboken's number. */
async function fillWrongPaper(page: Page) {
  const dialog = page.getByRole("dialog", {
    name: /Lägg till kanin|Registrera kanin/,
  });
  await gotoKaniner(page);
  await page
    .getByRole("button", { name: "+ Lägg till kanin" })
    .click({ timeout: 60000 });
  await pickParent(page, /^Mor/, "Visby Vilda");
  await pickParent(page, /^Far/, "Visby Test-04");
  const birth = page.getByRole("group", { name: /Födelsedatum/ });
  await birth.locator('[data-sectionindex="0"]').click();
  await birth.pressSequentially(BIRTH_DATE.replace(/-/g, ""));
  await birth.press("Tab");
  await dialog.getByLabel(/Antal födda/).fill("9");
  await dialog.getByLabel(/Levande i kullen efter 6 veckor/).fill("9");
  await expect(
    page.getByRole("dialog", { name: /Registrera kanin — G1274-24/ }),
  ).toBeVisible({ timeout: 15000 });
  const stamboken =
    (await page.locator("#register-rabbit-title").textContent())?.match(
      /G1274-\d+/,
    )?.[0] ?? "";
  // G1274-24 + litter + place: the paper says the next litter
  const litter = Number(stamboken.slice(8, -1));
  const paper = `G1274-24${litter + 1}${stamboken.slice(-1)}`;

  await dialog.getByRole("combobox").filter({ hasText: "Hona" }).click();
  await page.getByRole("option", { name: "Hona" }).click();
  await dialog.getByRole("textbox", { name: /^Färg/ }).first().fill("Blå");
  await dialog.getByRole("combobox").filter({ hasText: "Digitalt" }).click();
  await page.getByRole("option", { name: "Papper" }).click();
  // The paper's number is typed before Stamboken's is shown again
  await expect(
    page.getByRole("dialog", { name: "Lägg till kanin", exact: true }),
  ).toBeVisible();
  await dialog
    .getByRole("textbox", { name: /^Intygsnummer/ })
    .fill(`E2E-PN-${Date.now() % 1e10}`);
  await dialog.getByLabel(/Individnummer på pappret/).fill(paper);
  await expect(
    page.getByRole("dialog", { name: `Registrera kanin — ${stamboken}` }),
  ).toBeVisible({ timeout: 15000 });
  await dialog.getByRole("button", { name: "Registrera", exact: true }).click();

  const conflict = page.getByRole("dialog", {
    name: "Individnumret på pappret stämmer inte med Stamboken",
  });
  await expect(conflict).toBeVisible({ timeout: 30000 });
  await expect(conflict.getByText(`Pappret säger: ${paper}`)).toBeVisible();
  await expect(
    conflict.getByText(`Stamboken säger: ${stamboken}`),
  ).toBeVisible();
  await expect(
    conflict.getByText("Inget sparas förrän du väljer."),
  ).toBeVisible();
  return { dialog, conflict, stamboken, paper };
}

test.describe.serial("Pappersintygets individnummer mot Stambokens", () => {
  test("Pappret rättas: kaninen får Stambokens nummer", async ({ page }) => {
    const { dialog, conflict, stamboken } = await fillWrongPaper(page);
    await conflict.getByRole("button", { name: "Pappret rättas" }).click();
    await expect(dialog.getByText(`registrerad som ${stamboken}`)).toBeVisible({
      timeout: 30000,
    });
  });

  test("Pappret stämmer: instruktionen och meddelandet, inget sparas", async ({
    page,
  }) => {
    const { dialog, conflict, paper } = await fillWrongPaper(page);
    await conflict.getByRole("button", { name: "Pappret stämmer" }).click();
    await expect(conflict.getByText(/Inget har sparats/)).toBeVisible();
    const message = conflict.getByRole("textbox", {
      name: "Meddelande till genbanksansvarig",
    });
    expect(await message.inputValue()).toContain(
      `Pappersintyget säger ${paper}`,
    );
    await conflict.getByRole("button", { name: "Stäng" }).click();
    // Still the form: nothing was registered
    await expect(
      dialog.getByRole("button", { name: "Registrera", exact: true }),
    ).toBeVisible();
    await expect(dialog.getByText(/registrerad som/)).toHaveCount(0);
  });
});
