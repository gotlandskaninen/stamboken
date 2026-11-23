import { test, expect, type Page } from "@playwright/test";

// Tyck till (docs/tyck-till.md). The API runs with TYCK_TILL_GITHUB=logg, a
// fake GitHub that always succeeds. Runs as the owner from the project's
// storageState; the logged-out tests clear it.
test.use({ viewport: { width: 375, height: 740 } });

const TITLE = "Tyck till om Stamboken";
const APP = "/stamboken/min-besattning";
const LOGGED_OUT = { cookies: [], origins: [] };

const dialog = (page: Page) => page.getByRole("dialog", { name: TITLE });

async function noHorizontalScroll(page: Page) {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth > window.innerWidth,
  );
  expect(overflow).toBe(false);
}

async function fillIn(
  page: Page,
  typ: "Något fungerar inte" | "Jag önskar något",
) {
  await dialog(page).getByText(typ).click();
  await dialog(page)
    .getByLabel("Beskriv med egna ord")
    .fill("Knappen gör inget när jag trycker på den.");
}

test.describe("Tyck till, inloggad", () => {
  test("opens from the account menu", async ({ page }) => {
    await page.goto(APP);
    await page.getByRole("button", { name: "Account" }).click();
    await page.getByRole("menuitem", { name: "Tyck till" }).click();
    await expect(dialog(page)).toBeVisible();
    await noHorizontalScroll(page);
  });

  test("opens from the mobile menu", async ({ page }) => {
    await page.goto(APP);
    await page.getByRole("button", { name: "Meny" }).click();
    await page
      .getByRole("navigation", { name: "Mobilmeny" })
      .getByRole("button", { name: "Tyck till" })
      .click();
    await expect(dialog(page)).toBeVisible();
  });

  test("opens from the footer", async ({ page }) => {
    await page.goto(APP);
    await page
      .getByRole("contentinfo")
      .getByRole("button", { name: "Tyck till" })
      .click();
    await expect(dialog(page)).toBeVisible();
  });

  test("an empty form gives two field errors and focus on the first", async ({
    page,
  }) => {
    await page.goto(APP);
    await page
      .getByRole("contentinfo")
      .getByRole("button", { name: "Tyck till" })
      .click();
    await dialog(page).getByRole("button", { name: "Skicka" }).click();
    await expect(
      dialog(page).getByText(
        "Välj om något inte fungerar eller om du önskar något.",
      ),
    ).toBeVisible();
    await expect(
      dialog(page).getByText("Skriv några ord om vad det gäller."),
    ).toBeVisible();
    await expect(dialog(page).getByLabel("Något fungerar inte")).toBeFocused();
  });

  test("points at the page, previews the picture and points again", async ({
    page,
  }) => {
    await page.goto(APP);
    await page
      .getByRole("contentinfo")
      .getByRole("button", { name: "Tyck till" })
      .click();
    await dialog(page).getByRole("button", { name: "Peka på sidan" }).click();
    await expect(
      page.getByText("Tryck på det som är fel på sidan."),
    ).toBeVisible();
    await expect(dialog(page)).toBeHidden();

    const box = await page.locator("main h1, main h2").first().boundingBox();
    await page.mouse.click(box!.x + 8, box!.y + box!.height / 2);
    await expect(page.getByText(/Du har valt/)).toBeVisible();
    await page.getByRole("button", { name: "Använd" }).click();

    await expect(dialog(page)).toBeVisible();
    await expect(
      dialog(page).getByRole("img", { name: /Bild av sidan/ }),
    ).toBeVisible();
    await dialog(page).getByRole("button", { name: "Peka om" }).first().click();
    await expect(
      page.getByText("Tryck på det som är fel på sidan."),
    ).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(dialog(page)).toBeVisible();
    await expect(
      dialog(page).getByRole("img", { name: /Bild av sidan/ }),
    ).toBeVisible();
  });

  test("a private submission says that only the association reads it", async ({
    page,
  }) => {
    await page.goto(APP);
    await page
      .getByRole("contentinfo")
      .getByRole("button", { name: "Tyck till" })
      .click();
    await fillIn(page, "Något fungerar inte");
    await dialog(page).getByRole("button", { name: "Skicka" }).click();
    await expect(
      dialog(page).getByText("Tack! Vi har fått din synpunkt."),
    ).toBeVisible();
    await expect(
      dialog(page).getByText("Bara föreningen kan läsa den."),
    ).toBeVisible();
  });

  test("a public submission links to the issue", async ({ page }) => {
    await page.goto(APP);
    await page
      .getByRole("contentinfo")
      .getByRole("button", { name: "Tyck till" })
      .click();
    await fillIn(page, "Jag önskar något");
    await dialog(page).getByText("Alla", { exact: true }).click();
    await dialog(page).getByRole("button", { name: "Skicka" }).click();
    await expect(
      dialog(page).getByRole("link", { name: "Se ärendet" }),
    ).toHaveAttribute(
      "href",
      /^https:\/\/github\.com\/gotlandskaninen\/stamboken\/issues\/\d+$/,
    );
  });
});

test.describe("Tyck till, utloggad", () => {
  test.use({ storageState: LOGGED_OUT });

  test("opens from the sign-in page", async ({ page }) => {
    await page.goto("/stamboken-online");
    await page
      .locator("p", { hasText: "Kommer du inte in?" })
      .getByRole("button", { name: "Tyck till" })
      .click();
    await expect(dialog(page)).toBeVisible();
    await noHorizontalScroll(page);
  });

  test("opens from the verification page without a login", async ({ page }) => {
    await page.goto(
      "/stamboken/verifiera/00000000-0000-0000-0000-000000000000",
    );
    await page.getByRole("button", { name: "Tyck till" }).click();
    await expect(dialog(page)).toBeVisible();
    await expect(
      dialog(page).getByText("Vem får läsa det du skriver?"),
    ).toBeHidden();
  });

  test("asks for an address and answers to it", async ({ page }) => {
    await page.goto("/stamboken-online");
    await page
      .locator("p", { hasText: "Kommer du inte in?" })
      .getByRole("button", { name: "Tyck till" })
      .click();
    await fillIn(page, "Något fungerar inte");
    await dialog(page).getByRole("button", { name: "Skicka" }).click();
    await expect(dialog(page).getByText(/Skriv en e-postadress/)).toBeVisible();
    await expect(dialog(page).getByLabel("Din e-postadress")).toBeFocused();
    await dialog(page).getByLabel("Din e-postadress").fill("anna@exempel.se");
    await dialog(page).getByRole("button", { name: "Skicka" }).click();
    await expect(
      dialog(page).getByText("Vi svarar till anna@exempel.se."),
    ).toBeVisible();
    await expect(
      dialog(page).getByText("Bara föreningen kan läsa den."),
    ).toBeVisible();
  });
});
