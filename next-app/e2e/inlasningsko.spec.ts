import { expect, test, type Page } from "@playwright/test";
import { loginInline, TEST_USERS } from "../e2e-shared/auth";

// Inläsningskön från uppladdning till kaninens sida (docs/inkorg.md), med syntetiska data:
// uppfödaren (test-gk-owner, äger G1274) fotograferar ett intyg på en telefon, en genbanks-
// hjälpare (test-gk-helper, seedas av cli/create_test_users) tar ärendet och lägger in en
// ny kanin med Visby Vilda × Visby Viking som föräldrar, och uppfödaren ser pappersintyget.
// Filnamnet matchar inget mutation-/public-mönster, så specen körs i projektet owner-tests.
// Kullen (samma föräldrar och födelsedatum) återanvänds av en ny körning mot samma seed, som
// lägger nästa kanin i den: nio körningar, sedan färsk seed.
test.use({ viewport: { width: 390, height: 844 }, hasTouch: true });
test.setTimeout(180000);

const MOTHER = "G1274-2112";
const FATHER = "G1274-2111";
const BIRTH_DATE = "2025-06-10";

/** En vit sida med mörka textrader, ritad i webbläsaren (ingen riktig blankett). */
async function syntheticCertificate(page: Page): Promise<Buffer> {
  const base64 = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 1200;
    canvas.height = 1600;
    const ctx = canvas.getContext("2d")!;
    ctx.fillStyle = "#e8ecdf";
    ctx.fillRect(0, 0, 1200, 1600);
    ctx.fillStyle = "#14141e";
    for (let line = 0; line < 40; line++) {
      let x = 80;
      while (x < 1000) {
        const w = 20 + Math.floor(Math.random() * 90);
        ctx.fillRect(x, 120 + line * 34, w, 12);
        x += w + 14;
      }
    }
    return canvas.toDataURL("image/png").split(",")[1];
  });
  return Buffer.from(base64, "base64");
}

test("Ett intyg går från uppladdning till pappersintyg på kaninen", async ({
  page,
  browser,
  baseURL,
}) => {
  let itemId = "";
  let rabbit = "";

  await test.step("1. Uppfödaren laddar upp ett intyg på telefonen", async () => {
    await page.goto("/stamboken/inskick");
    await page.getByRole("link", { name: "Ladda upp intyg" }).click();
    await expect(
      page.getByRole("heading", { name: "Ladda upp intyg" }),
    ).toBeVisible();
    await page.getByTestId("inskick-files").setInputFiles({
      name: "intyg.png",
      mimeType: "image/png",
      buffer: await syntheticCertificate(page),
    });
    await expect(page.getByLabel("Valda filer")).toContainText("intyg.png");
    await page.getByRole("button", { name: "Skicka", exact: true }).click();
  });

  await test.step("2. Ärendet syns under Mina inskick med ärendenummer", async () => {
    await page.waitForURL(/\/stamboken\/inskick#arende-\d+/, {
      timeout: 60000,
    });
    itemId = page.url().match(/#arende-(\d+)/)![1];
    const card = page.locator(`#arende-${itemId}`);
    await expect(card).toContainText(`ärende ${itemId}`);
    await expect(card).toContainText("Mottaget");
  });

  const worker = await browser.newContext({
    baseURL,
    viewport: { width: 1280, height: 900 },
  });
  const desk = await worker.newPage();
  let documentId = "";
  try {
    await test.step("3. Hjälparen tar ärendet i Inkorg", async () => {
      await loginInline(desk, worker, TEST_USERS.helper);
      await desk.goto("/stamboken/inkorg");
      const row = desk.getByRole("row").filter({ hasText: `Ärende ${itemId}` });
      await row.getByRole("button", { name: "Jag tar den" }).click();
      await desk.waitForURL(new RegExp(`/stamboken/inkorg/${itemId}$`));
      await expect(
        desk.getByRole("heading", { name: `Ärende ${itemId}` }),
      ).toBeVisible();
      // The photo is drawn on a canvas once the queue-only original endpoint has answered.
      await expect
        .poll(() =>
          desk
            .locator("canvas")
            .first()
            .evaluate((canvas: HTMLCanvasElement) => canvas.width),
        )
        .toBeGreaterThan(300);
      const detail = await desk.request.get(`/api/v2/inkorg/${itemId}`);
      documentId = String((await detail.json()).documents[0].id);
    });

    await test.step("4. Hjälparen lägger in en ny kanin från intyget", async () => {
      // Stamboken's own number for the litter, as the owner's form would suggest it.
      const suggestion = await page.request.get(
        `/api/v2/individual/suggest-number?mother=${MOTHER}&father=${FATHER}&birth_date=${BIRTH_DATE}`,
      );
      expect(suggestion.ok()).toBeTruthy();
      const paperNumber: string = (await suggestion.json()).suggested;

      await desk.getByLabel("Individnummer på pappret").fill(paperNumber);
      await desk.getByLabel(/^Intygsnummer/).fill(`E2E-${Date.now() % 1e10}`);
      await desk.getByLabel(/^Namn/).fill("Testa Intyg");
      await desk.getByRole("combobox", { name: "Kön" }).click();
      await desk.getByRole("option", { name: "Hona" }).click();
      await desk.getByLabel("Födelsedatum").fill(BIRTH_DATE);
      await desk.getByRole("combobox", { name: "Färg" }).fill("Svart");
      await desk.getByRole("option", { name: "Svart", exact: true }).click();
      await desk.getByLabel(/^Mor/).fill(MOTHER);
      await desk.getByLabel(/^Far/).fill(FATHER);
      await desk.getByLabel("Antal födda").fill("9");
      await desk.getByLabel("Levande i kullen efter 6 veckor").fill("9");
      await desk.getByRole("button", { name: "Spara och nästa" }).click();

      await expect(desk.getByText("Dölj säljare och köpare")).toBeVisible({
        timeout: 30000,
      });
      rabbit = (await desk.getByText(/är sparad\./).textContent())!.match(
        /G1274-\d+/,
      )![0];
    });

    await test.step("5. Hjälparen bekräftar maskeringen", async () => {
      await desk.getByRole("button", { name: "Lägg till ruta" }).click();
      await desk
        .getByRole("button", { name: "Bekräfta maskningen och nästa" })
        .click();
      await expect(desk.getByText("Alla dokument är klara.")).toBeVisible({
        timeout: 30000,
      });
    });

    await test.step("6. Uppfödaren ser Pappersintyg på kaninen och ärendet som klart", async () => {
      await page.goto(`/stamboken/individ/${rabbit}`);
      await expect(
        page.getByRole("heading", { name: "Pappersintyg" }),
      ).toBeVisible({ timeout: 30000 });
      await expect(
        page.getByRole("img", {
          name: /Pappersintyg, klicka för full storlek/,
        }),
      ).toBeVisible();
      await page.goto("/stamboken/inskick");
      const card = page.locator(`#arende-${itemId}`);
      await expect(card).toContainText("Klart");
      await expect(card).toContainText(rabbit);
    });

    await test.step("7. Originalet är stängt för uppfödaren och ligger inte bland de öppna filerna", async () => {
      const original = `/api/v2/inkorg/${itemId}/dokument/${documentId}/original`;
      expect((await desk.request.get(original)).status()).toBe(200);
      expect((await page.request.get(original)).status()).toBe(403);
      // Nobody logged in, in a context of its own.
      const anonymous = await browser.newContext({ baseURL });
      try {
        expect([401, 403]).toContain(
          (await anonymous.request.get(original)).status(),
        );
        // Originals live outside the folder nginx serves (/uppladdningar/); their names are random, so
        // this only shows that nothing of the queue is served from there. The folder rule is a pytest.
        for (const path of [
          "/uppladdningar/inkorg/original/",
          `/uppladdningar/inkorg/original/${documentId}.jpg`,
        ])
          expect((await page.request.get(path)).status()).toBe(404);
      } finally {
        await anonymous.close();
      }
      // The masked copy, by contrast, is the one thing the owner may fetch.
      const copy = await page.request.get(
        `/api/v2/individual/${rabbit}/paper-certificate`,
      );
      expect(copy.status()).toBe(200);
      expect(copy.headers()["cache-control"]).toContain("no-store");
    });
  } finally {
    await worker.close();
  }
});
