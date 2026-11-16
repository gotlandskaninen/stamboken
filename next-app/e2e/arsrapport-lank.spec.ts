import * as fs from "fs";
import * as path from "path";
import {
  expect,
  test,
  type BrowserContext,
  type Locator,
  type Page,
} from "@playwright/test";
import { loginInline } from "../e2e-shared/auth";

// The yearly report through the personal link /rapport#<token> (step 3), on the Mellerud herds M9201, M9202 and M9203
// of `flask seed arsrapport`, whose links `flask seed arsrapport-lankar` writes to e2e/.auth/arsrapport-lankar.json.
// Nobody is signed in. Serial, and it assumes a freshly seeded database, as CI's is.
test.describe.configure({ mode: "serial", retries: 0 });
test.use({
  viewport: { width: 375, height: 812 },
  hasTouch: true,
  storageState: { cookies: [], origins: [] },
});
test.setTimeout(120_000);

const FIXTURE = path.join(
  process.cwd(),
  "e2e",
  ".auth",
  "arsrapport-lankar.json",
);
const links: Record<string, string> = fs.existsSync(FIXTURE)
  ? JSON.parse(fs.readFileSync(FIXTURE, "utf8"))
  : {};
if (!fs.existsSync(FIXTURE) && process.env.CI)
  throw new Error(`${FIXTURE} is missing: seed it with arsrapport-lankar`);
test.skip(
  !fs.existsSync(FIXTURE),
  "no links fixture: run `flask seed arsrapport-lankar`",
);

const tokenOf = (herd: string) => links[herd].split("#")[1];
const SEND = /^Skicka (årsrapporten|ändringarna)$/;
const NO_DISEASE = "Inga sjukdomsfall eller defekter";
const rows = (page: Page) => page.locator('fieldset[id^="rabbit-"]');
const kvar = (r: Locator) => r.getByRole("radio", { name: "Finns kvar" });
const weight = (r: Locator) => r.getByLabel("Vikt", { exact: true });
const hydrated = (page: Page) =>
  page.waitForFunction(
    () =>
      Object.keys(document.querySelector('fieldset[id^="rabbit-"]') ?? {}).some(
        (k) => k.startsWith("__reactFiber"),
      ),
    undefined,
    { timeout: 90_000 },
  );

// Every request of the page: neither its URL nor its Referer may carry a token.
function watchRequests(page: Page, tokens: string[]) {
  const urls: string[] = [];
  const leaks: string[] = [];
  page.on("request", (req) => {
    urls.push(req.url());
    const seen = `${req.url()} ${req.headers()["referer"] ?? ""}`;
    if (tokens.some((t) => seen.includes(t) || seen.includes(t.split(".")[1])))
      leaks.push(req.url());
  });
  return { urls, leaks };
}

async function fillAllAndSend(page: Page) {
  await expect(rows(page)).toHaveCount(6);
  await hydrated(page);
  for (const n of [2411, 2412, 2413, 2414, 2415]) {
    const r = rows(page).filter({ hasText: `M9201-${n}` });
    await kvar(r).check();
    await weight(r).fill("2,8");
  }
  await kvar(rows(page).filter({ hasText: "M9201-2520" })).check();
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await page.getByRole("button", { name: SEND }).click();
  await expect(page.getByText(/^Inskickad/)).toBeVisible({ timeout: 30_000 });
}

// Steps 1-5 are one browser: the code session lives in its cookie.
let shared: Page;
test.beforeAll(async ({ browser }) => {
  shared = await (await browser.newContext()).newPage();
});
test.afterAll(async () => {
  await shared.context().close();
});

test("0. The genebank manager has activated the round", async ({
  page,
  context,
}) => {
  await loginInline(page, context, {
    username: "seed-mk-mgr@test.local",
    password: "seed-mk-pass",
  });
  await page.goto("/stamboken/arsrapport/status/2025");
  const activate = page.getByRole("button", { name: "Aktivera", exact: true });
  if (await activate.isVisible()) await activate.click();
  await expect(page.getByText(/^Aktiverad /)).toBeVisible();
  await context.clearCookies(); // the rest is anonymous
});

test("1. The link opens the report and the token leaves the address bar", async () => {
  const page = shared;
  const seen = watchRequests(page, [tokenOf("M9201")]);
  // The token is out of the address bar by the end of parsing, before the application starts.
  await page.addInitScript(() => {
    document.addEventListener("DOMContentLoaded", () => {
      (window as unknown as { __hashAtParse: string }).__hashAtParse =
        location.hash;
    });
  });
  await page.goto(links["M9201"]);
  await expect(page.getByText("Besättning M9201")).toBeVisible();
  expect(
    await page.evaluate(
      () => (window as unknown as { __hashAtParse: string }).__hashAtParse,
    ),
  ).toBe("");
  expect(
    await page.evaluate(
      () => (window as unknown as { __rapportToken?: string }).__rapportToken,
    ),
  ).toBeUndefined();
  await expect(page.getByText("Besättning M9201")).toBeVisible(); // no redirect to sign-in: the middleware leaves /rapport alone
  expect(page.url()).not.toContain("#");
  expect(new URL(page.url()).pathname).toBe("/rapport");
  expect(await page.evaluate(() => location.hash)).toBe("");
  await expect(page.getByText("Besättning M9201")).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(seen.leaks).toEqual([]);
  expect(
    seen.urls.filter((u) => u.includes("/api/v2/rapport/oppna")),
  ).toHaveLength(1);
  // The report is the herd's own, with no link into the signed-in app.
  await expect(page.locator('a[href^="/stamboken"]')).toHaveCount(0);
});

test("2. Fill in the rows as Typ A and send", async () => {
  const page = shared;
  await page.goto("/rapport"); // the session from step 1, no hash
  await fillAllAndSend(page);
});

test("3. Withdraw, then send again", async () => {
  const page = shared;
  await page.goto("/rapport");
  await expect(page.getByText(/^Inskickad/)).toBeVisible();
  await page.getByRole("button", { name: "Dra tillbaka", exact: true }).click();
  await page.getByRole("button", { name: "Dra tillbaka rapporten" }).click();
  await expect(page.getByRole("button", { name: SEND })).toBeVisible();
  await expect(page.getByText(/^Inskickad/)).toHaveCount(0);
  await fillAllAndSend(page);
});

test("4. A link that does not work shows the page for it", async () => {
  const page = shared;
  // shortcut: a forged token stands in for a revoked one; no route revokes a code before step 9.
  // From the open /rapport of step 3: a hash change alone, no new load.
  await page.goto("/rapport#1.AAAAAAAAAAAAAAAAAAAAAA");
  await expect(page.getByText("Länken gäller inte längre.")).toBeVisible();
  expect(page.url()).not.toContain("#");
  expect(new URL(page.url()).pathname).toBe("/rapport/ogiltig");
});

test("5. Two links open: /rapport lists both", async () => {
  const page = shared;
  await page.goto(links["M9202"]); // the session holds M9201 already
  await expect(page.getByText("Besättning M9202")).toBeVisible();
  await page.goto("/rapport");
  await expect(
    page.getByRole("heading", { name: "Välj besättning" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: /^M9201/ })).toBeVisible();
  await page.getByRole("link", { name: /^M9202/ }).click();
  await expect(page.getByText("Besättning M9202")).toBeVisible();
});

test("5b. A link opened inside the open page is exchanged too", async () => {
  const page = shared; // on M9202's report: only the hash changes
  await page.evaluate((hash) => (location.hash = hash), tokenOf("M9201"));
  await expect(page.getByText("Besättning M9201")).toBeVisible();
  expect(page.url()).not.toContain("#");
});

test("6. The test mail's link #prov opens nothing", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  const seen = watchRequests(page, []);
  await page.goto("/rapport#prov");
  await expect(
    page.getByText(
      "Provlänken fungerar. I det riktiga mejlet öppnar länken besättningens årsrapport.",
    ),
  ).toBeVisible();
  expect(page.url()).not.toContain("#");
  expect(seen.urls.filter((u) => u.includes("/api/v2/rapport/oppna"))).toEqual(
    [],
  );
  await context.close();
});

test("7. A browser that drops cookies gets the cookie text", async ({
  browser,
}) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.route("**/api/v2/rapport/oppna", async (route) => {
    const response = await route.fetch(); // route.fetch keeps the cookie in the context: take it out again
    await context.clearCookies();
    const headers = { ...response.headers() };
    delete headers["set-cookie"];
    await route.fulfill({ response, headers });
  });
  await page.goto(links["M9203"]);
  await expect(
    page.getByText(/Din webbläsare tog inte emot inloggningen/),
  ).toBeVisible();
  await context.close();
});

test("8. The session ends in the middle of input and the link continues", async ({
  browser,
}) => {
  const context: BrowserContext = await browser.newContext();
  const page = await context.newPage();
  await page.goto(links["M9203"]);
  await expect(rows(page)).toHaveCount(6);
  await hydrated(page);
  const first = rows(page).filter({ hasText: "M9203-2411" });
  await kvar(first).check();
  await weight(first).fill("2,8");
  await expect(page.getByText(/Sparat \d/).first()).toBeVisible({
    timeout: 30_000,
  });
  await context.clearCookies(); // the two hours are over
  const second = rows(page).filter({ hasText: "M9203-2412" });
  await kvar(second).check();
  await weight(second).fill("2,9");
  await expect(
    page.getByText(/Sidan stängdes efter två timmar/).first(),
  ).toBeVisible({
    timeout: 30_000,
  });
  await page.goto(links["M9203"]); // the same link again
  await expect(rows(page)).toHaveCount(6);
  await hydrated(page);
  await expect(
    kvar(rows(page).filter({ hasText: "M9203-2411" })),
  ).toBeChecked();
  await expect(
    weight(rows(page).filter({ hasText: "M9203-2412" })),
  ).toHaveValue("2,9"); // kept in the browser, and saved again
  await context.close();
});
