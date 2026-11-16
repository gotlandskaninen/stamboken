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

/** A 40 x 40 px smooth gradient: too small and too soft, so the API warns about it. */
async function tinyBlurryImage(page: Page): Promise<Buffer> {
  const base64 = await page.evaluate(() => {
    const canvas = document.createElement("canvas");
    canvas.width = 40;
    canvas.height = 40;
    const ctx = canvas.getContext("2d")!;
    const g = ctx.createLinearGradient(0, 0, 40, 40);
    g.addColorStop(0, "#808080");
    g.addColorStop(1, "#909090");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, 40, 40);
    return canvas.toDataURL("image/png").split(",")[1];
  });
  return Buffer.from(base64, "base64");
}

const myItems = async (page: Page): Promise<number> =>
  (await (await page.request.get("/api/v2/inkorg/mina-inskick")).json()).items
    .length;

test("Ett intyg går från uppladdning till pappersintyg på kaninen", async ({
  page,
  browser,
  baseURL,
}) => {
  let itemId = "";
  let rabbit = "";

  await test.step("0. Ett suddigt foto lagras inte förrän uppfödaren väljer Skicka ändå", async () => {
    const before = await myItems(page);
    await page.goto("/stamboken/inskick/ny");
    await page.getByTestId("inskick-files").setInputFiles({
      name: "suddigt.png",
      mimeType: "image/png",
      buffer: await tinyBlurryImage(page),
    });
    await page.getByRole("button", { name: "Skicka", exact: true }).click();
    await expect(
      page.getByText(/Bilden (har låg upplösning|ser suddig)/).first(),
    ).toBeVisible({
      timeout: 60000,
    });
    expect(await myItems(page)).toBe(before);
    await page.getByRole("button", { name: "Skicka ändå" }).click();
    await page.waitForURL(/\/stamboken\/inskick#arende-\d+/, {
      timeout: 60000,
    });
    expect(await myItems(page)).toBe(before + 1);
  });

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
    // One upload: the API either stores the photo or answers 409 with warnings
    // and stores nothing, and then "Skicka ändå" sends the same photo again.
    const sendAnyway = page.getByRole("button", { name: "Skicka ändå" });
    await Promise.race([
      page.waitForURL(/\/stamboken\/inskick#arende-\d+/, { timeout: 60000 }),
      sendAnyway.waitFor({ timeout: 60000 }),
    ]);
    if (await sendAnyway.isVisible()) await sendAnyway.click();
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
      const canvasSize = () =>
        desk
          .locator("canvas")
          .first()
          .evaluate((c: HTMLCanvasElement) => [c.width, c.height]);
      // Read the photo first and turn it for reading: nothing is saved before the case is taken.
      await desk.goto(`/stamboken/inkorg/${itemId}`);
      await expect
        .poll(async () => (await canvasSize())[0])
        .toBeGreaterThan(300);
      await desk.getByRole("button", { name: /Vrid höger/ }).click();
      await expect
        .poll(async () => {
          const [w, h] = await canvasSize();
          return w > h;
        })
        .toBe(true);
      await desk
        .getByLabel("Ärendet")
        .getByRole("button", { name: "Jag tar den" })
        .click();
      // The unsaved turn is dropped once the item is taken: the view starts from the stored 0.
      await expect
        .poll(async () => {
          const [w, h] = await canvasSize();
          return w < h;
        })
        .toBe(true);
      // Now a turn is saved with the document.
      await desk.getByRole("button", { name: /Vrid höger/ }).click();
      await expect
        .poll(async () => {
          const [w, h] = await canvasSize();
          return w > h;
        })
        .toBe(true);
      // The photo is drawn on a canvas once the queue-only original endpoint has answered.
      await expect
        .poll(() =>
          desk
            .locator("canvas")
            .first()
            .evaluate((canvas: HTMLCanvasElement) => canvas.width),
        )
        .toBeGreaterThan(300);
      const readDoc = async () =>
        (await (await desk.request.get(`/api/v2/inkorg/${itemId}`)).json())
          .documents[0];
      documentId = String((await readDoc()).id);
      await expect.poll(async () => (await readDoc()).rotation).toBe(90);
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
      // The masking starts from the stored turn: the photo is still lying on its side.
      expect(
        await desk
          .locator("canvas")
          .first()
          .evaluate((c: HTMLCanvasElement) => c.width > c.height),
      ).toBe(true);
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

    await test.step("8. Kopian är vriden åt samma håll som i maskningen och rutan är svart", async () => {
      // Read the copy the way the owner's browser shows it, pixel by pixel.
      const copy = await page.evaluate(async (number) => {
        const res = await fetch(
          `/api/v2/individual/${number}/paper-certificate`,
        );
        const bitmap = await createImageBitmap(await res.blob());
        const canvas = document.createElement("canvas");
        canvas.width = bitmap.width;
        canvas.height = bitmap.height;
        const ctx = canvas.getContext("2d")!;
        ctx.drawImage(bitmap, 0, 0);
        // Fractions of the copy: the default box (x .35-.65, y .45-.55) and a corner of paper.
        const at = (fx: number, fy: number) =>
          Array.from(
            ctx
              .getImageData(
                Math.floor(fx * canvas.width),
                Math.floor(fy * canvas.height),
                1,
                1,
              )
              .data.slice(0, 3),
          );
        return {
          width: canvas.width,
          height: canvas.height,
          inside: [
            [0.36, 0.46],
            [0.64, 0.46],
            [0.36, 0.54],
            [0.64, 0.54],
            [0.5, 0.5],
          ].map(([x, y]) => at(x, y)),
          paper: at(0.02, 0.02),
        };
      }, rabbit);
      // Turned 90 degrees: landscape, and a box wider than tall, not the other way round.
      expect(copy.width).toBeGreaterThan(copy.height);
      for (const px of copy.inside) expect(Math.max(...px)).toBeLessThan(20);
      expect(Math.min(...copy.paper)).toBeGreaterThan(150);
    });

    await test.step("9. Uppfödaren hör inte hemma i Inkorg", async () => {
      const res = await page.goto("/stamboken/inkorg");
      expect(res?.status()).toBe(404);
      await expect(
        page.getByRole("heading", { name: "Sidan kunde inte hittas" }),
      ).toBeVisible();
    });
  } finally {
    await worker.close();
  }
});
