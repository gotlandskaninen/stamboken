import { test, expect, type Page } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Skärmbilder till guiden för matrikeln (content/matrikel-guide/). Går igenom
// flödet en gång med påhittade personer: en ansökan skickas in och godkänns,
// ett medlemskap läggs in för hand och får en familjemedlem. Körs för hand mot
// en NYSTARTAD seedad e2e-stack (en andra körning lägger in samma personer en
// gång till), aldrig i CI och aldrig mot prod eller demo:
//
//   MANUAL_BASE_URL=http://localhost:3010 pnpm exec playwright test \
//     --config playwright.manual-screenshots.config.ts \
//     e2e/manual/matrikel-guide-screenshots.spec.ts

const OUT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../content/matrikel-guide",
);
const ADMIN = { username: "test-admin", password: "test-admin-pass" };
// Påhittade personer på example.com-adresser.
const APPLICANT = {
  first: "Anna",
  last: "Exempel",
  email: "anna.exempel@example.com",
};

test.describe.configure({ mode: "serial" });
test.use({ viewport: { width: 1280, height: 800 } });
test.beforeEach(async ({ page }) => {
  // The beta banner takes room on every picture; mark it closed as a reader would.
  await page.addInitScript(() =>
    localStorage.setItem("herdbook-wip-banner-dismissed", "1"),
  );
});

async function shot(page: Page, name: string, fullPage = false) {
  await page.addStyleTag({
    content: "nextjs-portal { display: none !important; }",
  });
  await page.waitForTimeout(600);
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage });
}

async function loginAdmin(page: Page) {
  const res = await page.request.post("/api/login", { data: ADMIN });
  expect(res.ok(), `login: ${res.status()}`).toBeTruthy();
  // sb_mode=prod: riktiga stamboken, utan testmiljö-banner (som screenshots.spec.ts).
  await page.context().addCookies([
    {
      name: "sb_mode",
      value: "prod",
      domain: "localhost",
      path: "/",
      sameSite: "Lax",
    },
  ]);
}

test("en ansökan kommer in", async ({ page }) => {
  await page.goto("/ansok");
  await page.getByLabel(/Förnamn/).fill(APPLICANT.first);
  await page.getByLabel(/Efternamn/).fill(APPLICANT.last);
  await page.getByLabel(/^E-post/).fill(APPLICANT.email);
  await page.getByLabel(/Gatuadress/).fill("Exempelvägen 12");
  await page.getByLabel(/^Postnummer/).fill("62141");
  await page.getByLabel(/^Postort/).click();
  await page.getByLabel(/^Postort/).fill("Visby");
  await page
    .getByLabel(/Berätta kort om dig själv/)
    .fill("Jag har gotlandskaniner hemma och vill bli genbanksbesättning.");
  await page.getByLabel(/GDPR/).check();
  await page.getByRole("button", { name: /Skicka ansökan/ }).click();
  await expect(page.getByText(/Tack för din ansökan/)).toBeVisible({
    timeout: 15000,
  });
});

test("ansökan granskas och godkänns", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/medlem/ansokningar", { waitUntil: "networkidle" });
  await expect(
    page.getByText(`${APPLICANT.first} ${APPLICANT.last}`),
  ).toBeVisible();
  await shot(page, "ansokningar");

  await page.getByRole("button", { name: "Account" }).click();
  await expect(page.getByRole("menuitem", { name: "Matrikel" })).toBeVisible();
  await shot(page, "meny");
  await page.keyboard.press("Escape");

  await page
    .getByRole("link", { name: `${APPLICANT.first} ${APPLICANT.last}` })
    .click();
  await expect(
    page.getByRole("heading", { name: /Ansökan från/ }),
  ).toBeVisible();
  await shot(page, "ansokan", true);

  await page.getByRole("button", { name: "Godkänn", exact: true }).click();
  await expect(page.getByText("Godkänna ansökan?")).toBeVisible();
  await shot(page, "ansokan-godkann");
  await page
    .getByRole("dialog")
    .getByRole("button", { name: "Godkänn" })
    .click();
  await page.waitForURL(/\/medlem\/ansokningar$/);
});

test("ett medlemskap läggs in för hand", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/medlem/matrikel", { waitUntil: "networkidle" });
  await page.getByRole("button", { name: "Nytt medlemskap" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Förnamn").fill("Karin");
  await dialog.getByLabel("Efternamn").fill("Prov");
  await dialog.getByLabel("E-post").fill("karin.prov@example.com");
  await dialog.getByLabel("Gatuadress").fill("Provgatan 3");
  await dialog.getByLabel("Postnummer").fill("46430");
  await dialog.getByLabel("Postort").fill("Mellerud");
  await shot(page, "nytt-medlemskap");
  await dialog.getByRole("button", { name: "Skapa" }).click();
  await expect(dialog).toBeHidden();
  await page.goto("/medlem/matrikel", { waitUntil: "networkidle" });
  await shot(page, "matrikel");
});

test("medlemskapets sida, adress och betalning", async ({ page }) => {
  await loginAdmin(page);
  await page.goto(`/medlem/matrikel?search=${APPLICANT.last}`, {
    waitUntil: "networkidle",
  });
  await page.getByRole("link").filter({ hasText: /^\d+$/ }).first().click();
  await expect(
    page.getByRole("heading", { name: /Medlemskap nr/ }),
  ).toBeVisible();
  await shot(page, "medlemskap");

  const form = page.locator("section").filter({
    has: page.getByRole("heading", { name: "Medlemskap", exact: true }),
  });
  await form.getByLabel("Betalningsnotering").fill("Betalt 2026-11-16 Swish");
  await form.scrollIntoViewIfNeeded();
  await form.screenshot({ path: path.join(OUT, "medlemskap-formular.png") });
  await form.getByRole("button", { name: "Spara" }).click();
  await expect(page.getByText("Medlemskapet sparat")).toBeVisible();

  await page.getByRole("button", { name: "Lägg till person" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Förnamn").fill("Olle");
  await dialog.getByLabel("Efternamn").fill("Exempel");
  await shot(page, "lagg-till-person");
  await dialog.getByRole("button", { name: "Spara" }).click();
  await expect(page.getByText("Person tillagd")).toBeVisible();
  await expect(page.getByText("Person tillagd")).toBeHidden({ timeout: 15000 });

  await page
    .getByRole("button", { name: "Fler åtgärder för Olle Exempel" })
    .click();
  await shot(page, "person-atgarder");
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "Avsluta medlemskap" }).click();
  await shot(page, "avsluta-medlemskap");
  await page.getByRole("button", { name: "Avbryt" }).click();
});

test("statistik", async ({ page }) => {
  await loginAdmin(page);
  await page.goto("/medlem/statistik", { waitUntil: "networkidle" });
  await shot(page, "statistik");
});
