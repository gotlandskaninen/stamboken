import {
  expect,
  type BrowserContext,
  test,
  type Locator,
  type Page,
} from "@playwright/test";
import { loginInline as loginOnce } from "../e2e-shared/auth";

// The yearly report 2025 as different kinds of users, on the synthetic Mellerud herds of `flask seed arsrapport`
// (M9001-M9006, M9101, M9102), at 375 px. The Gotland round of arsrapport-runda.spec.ts is never touched: the two
// files use different genebanks and can run side by side.
//
// The steps change shared state and depend on each other, so the file runs serially and never retries. It assumes a
// freshly seeded database, as CI's is. To run it again locally, `docker compose down -v` and seed again.
test.describe.configure({ mode: "serial", retries: 0 });
test.use({ viewport: { width: 375, height: 812 }, hasTouch: true });
test.setTimeout(120_000);

const API_URL = process.env.E2E_API_URL ?? "http://localhost:9090";
const USERS = {
  manager: { username: "seed-mk-mgr@test.local", password: "seed-mk-pass" },
  owner: {
    username: "seed-mk-uppfodare@test.local",
    password: "seed-mk-uppfodare-pass",
  },
  helper: {
    username: "seed-mk-hjalp@test.local",
    password: "seed-mk-hjalp-pass",
  },
};
// SUBMIT_TIMEOUT_MS in arsrapport/lib.ts: Skicka answers within it.
const SUBMIT_TIMEOUT_MS = 30_000;
const NO_DISEASE = "Inga sjukdomsfall eller defekter";
const SEND = /^Skicka (årsrapporten|ändringarna)$/;

// CI turns the login limit off (RATELIMIT_ENABLED=false); a local stack allows 5 logins a minute, and this file
// logs in more often than that. A refused login waits for the minute to pass.
async function loginInline(
  page: Page,
  context: BrowserContext,
  user: (typeof USERS)[keyof typeof USERS],
) {
  for (let attempt = 1; ; attempt++) {
    try {
      return await loginOnce(page, context, user);
    } catch (e) {
      if (attempt >= 4 || !String(e).includes("failed: 429")) throw e;
      await page.waitForTimeout(20_000);
    }
  }
}

const rows = (page: Page) => page.locator('fieldset[id^="rabbit-"]');
const rabbit = (page: Page, number: string) =>
  rows(page).filter({ hasText: number });
const row = (page: Page, herd: string) =>
  page.getByRole("row").filter({ hasText: herd });
const numbers = (herd: string, ...suffixes: number[]) =>
  suffixes.map((n) => `${herd}-${n}`);
const range = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, i) => from + i);
const kvar = (r: Locator) => r.getByRole("radio", { name: "Finns kvar" });
const weight = (r: Locator) => r.getByLabel("Vikt", { exact: true });
const submitted = (page: Page) =>
  expect(page.getByText(/^Inskickad/)).toBeVisible({
    timeout: SUBMIT_TIMEOUT_MS,
  });
const shot = async (page: Page, name: string) => {
  if (process.env.TYPER_SHOTS)
    await page.screenshot({
      path: `${process.env.TYPER_SHOTS}/${name}.png`,
      fullPage: true,
    });
};
// A tap before React has hydrated the page is lost, and on a slow net hydration comes late: wait for it.
const hydrated = (page: Page) =>
  page.waitForFunction(
    () =>
      Object.keys(document.querySelector('fieldset[id^="rabbit-"]') ?? {}).some(
        (k) => k.startsWith("__reactFiber"),
      ),
    undefined,
    { timeout: 90_000 },
  );
const noSideScroll = (page: Page) =>
  page.evaluate(
    () =>
      document.documentElement.scrollWidth <=
      document.documentElement.clientWidth + 1,
  );

// Type A counts taps: every action on a control goes through here. A fill is one tap; goto, login and scrolling
// are none.
let taps = 0;
const tap = {
  click: (l: Locator) => (taps++, l.click()),
  check: (l: Locator) => (taps++, l.check()),
  select: (l: Locator, v: string) => (taps++, l.selectOption(v)),
  fill: (l: Locator, v: string) => (taps++, l.fill(v)),
  press: (l: Locator, k: string) => (taps++, l.press(k)),
};

// All rows "Finns kvar" and a weight on every adult (rabbits born in 2025 need none), then Skicka.
async function reportAllKvar(page: Page, herd: string) {
  await page.goto(`/stamboken/arsrapport/${herd}/2025`);
  await expect(rows(page)).toHaveCount(6);
  await hydrated(page);
  for (const n of range(2411, 2415)) {
    const r = rabbit(page, `${herd}-${n}`);
    await kvar(r).check();
    await weight(r).fill("2,8");
  }
  await kvar(rabbit(page, `${herd}-2520`)).check();
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await page.getByRole("button", { name: SEND }).click();
  await submitted(page);
}

// The stored report of a herd, read as the genebank manager straight from Flask.
async function storedReport(page: Page, herd: string) {
  const res = await page.request.get(
    `${API_URL}/api/v2/arsrapport/besattning/${herd}/2025`,
  );
  expect(res.ok()).toBe(true);
  return res.json();
}

async function takeItem(page: Page, herd: string) {
  await page.goto("/stamboken/inkorg");
  await row(page, herd)
    .getByRole("button", { name: "Jag tar den" })
    .first()
    .click();
  await page.getByRole("link", { name: "Mata in årsrapporten" }).click();
  await page.waitForURL(
    new RegExp(`/stamboken/arsrapport/${herd}/2025\\?post=\\d+`),
  );
}

// Paper entry: the number goes in the search box, Enter makes a row; then its choice and weight.
async function enterPaperRow(
  page: Page,
  herd: string,
  index: number,
  suffix: number,
  weightText: string | null,
) {
  const number = page.getByLabel(`Nummer efter ${herd}-`);
  await number.fill(String(suffix));
  await number.press("Enter");
  const r = rows(page).nth(index);
  await kvar(r).check();
  if (weightText) await weight(r).fill(weightText);
}

// Dead and sold rows of a big herd: the dead one in October, the sold ones to a buyer outside the genebank.
async function markDead(r: Locator, month: string) {
  await r.getByRole("radio", { name: "Död", exact: true }).check();
  await r.locator('select[id^="month-"]').selectOption(month);
}
async function markSold(
  page: Page,
  r: Locator,
  to: { outside: string } | { herd: string },
  when: { ar: string; manad: string; dag?: string } = {
    ar: "2025",
    manad: "8",
  },
) {
  await r.getByRole("radio", { name: "Såld" }).click(); // opens the dialog; the radio is set when it is saved
  const dialog = page.getByRole("dialog");
  if ("herd" in to) {
    await dialog
      .getByRole("combobox", { name: "Köparens besättning" })
      .fill(to.herd);
    await page
      .getByRole("option", { name: new RegExp(`^${to.herd} `) })
      .click();
  } else {
    await dialog.getByRole("radio", { name: "Utanför genbanken" }).check();
    await dialog.getByLabel("Köparens namn").fill(to.outside);
    await dialog.getByLabel("Köparens ort").fill("Mellerud");
  }
  await dialog.getByLabel("År").selectOption(when.ar);
  await dialog.getByLabel("Månad").selectOption(when.manad);
  if (when.dag) await dialog.getByLabel("Dag (frivillig)").fill(when.dag);
  await dialog.getByRole("button", { name: "Spara försäljningen" }).click();
  await expect(dialog).toBeHidden();
}

test("1. Genbanksansvarig aktiverar rundan för Mellerudskanin", async ({
  page,
  context,
}) => {
  await loginInline(page, context, USERS.manager);
  await page.goto("/stamboken/arsrapport/status/2025");
  await expect(
    page.getByRole("heading", {
      name: "Rundan 2025 är inte aktiverad för Mellerudskanin",
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Aktivera", exact: true }).click();
  await expect(page.getByText(/^Aktiverad /)).toBeVisible();

  // Nobody has reported: the manager sees the herds with the phone numbers of their main members. Spec 5.14:
  // "Att ringa" holds bounced mail, drafts after 29 January and unstated rabbits that decide the support, so a herd
  // that has not started is in the full list and not in "Att ringa" (not even M9002 and M9005).
  await page.goto("/stamboken/arsrapport/status/2025");
  await expect(row(page, "M9002")).toContainText("0700000002");
  await expect(row(page, "M9005")).toContainText("0700000005");
  await expect(row(page, "M9001")).toContainText("Ej rapporterad");
  await shot(page, "status-fore-rapporter");
  await page.goto("/stamboken/arsrapport/status/2025?filter=att_ringa");
  await expect(page.getByText("Inga besättningar att ringa.")).toBeVisible();
});

test("2. Hjälparen ser inte telefonnummer", async ({ page, context }) => {
  await loginInline(page, context, USERS.helper);
  const phones = ["0700000002", "0700000005"];
  for (const path of [
    "/stamboken/arsrapport/status/2025",
    "/stamboken/arsrapport/status/2025?filter=alla",
    "/stamboken/inkorg",
  ]) {
    await page.goto(path);
    // The page has loaded with the herds on it, so the missing numbers mean something.
    await expect(
      page.getByText("M9002").or(page.getByText("M9005")).first(),
    ).toBeVisible();
    for (const phone of phones)
      await expect(page.locator("body")).not.toContainText(phone);
  }
  await expect(page.locator('a[href^="tel:"]')).toHaveCount(0);
});

test("3. Typ A: medianbesättning i mobilen", async ({ page, context }) => {
  await loginInline(page, context, USERS.owner);
  await page.goto("/stamboken/arsrapport/M9001/2025");
  await expect(rows(page)).toHaveCount(6);
  await hydrated(page);
  taps = 0;
  const start = Date.now(); // the first tap follows at once

  for (const n of range(2411, 2415)) {
    const r = rabbit(page, `M9001-${n}`);
    await tap.check(kvar(r));
    await tap.fill(weight(r), "2,8");
  }
  await tap.check(kvar(rabbit(page, "M9001-2520")));
  await tap.check(page.getByRole("radio", { name: NO_DISEASE }));
  await shot(page, "typ-a-formular");
  await tap.click(page.getByRole("button", { name: SEND }));
  await submitted(page);
  const seconds = Number(((Date.now() - start) / 1000).toFixed(1));
  await shot(page, "typ-a-kvitto");

  test
    .info()
    .annotations.push(
      { type: "tryck", description: String(taps) },
      { type: "sekunder", description: String(seconds) },
    );
  expect(taps).toBeLessThanOrEqual(20);
});

test("4. Typ B: ovan användare, långsamt nät och smal skärm", async ({
  page,
  context,
}) => {
  test.setTimeout(240_000); // two page loads over Slow 3G
  await loginInline(page, context, USERS.owner);
  // 320 px is the WCAG reflow width and a small phone. Large text is tested on a real phone
  // (docs/arsrapport/testmanus-anvandartyper.md in stamboken-drift): the report's CSS is in px, so a root font
  // size does not grow it.
  await page.setViewportSize({ width: 320, height: 640 });
  // Side scroll is noted, not asserted at once, so the later steps still run and test 11 finds M9002 submitted.
  let overflow = 0;
  const checkScroll = async () => {
    if (!(await noSideScroll(page))) overflow++;
  };
  // Slow 3G: 400 ms latency, about 500 kbit/s each way.
  const cdp = await context.newCDPSession(page);
  await cdp.send("Network.enable");
  await cdp.send("Network.emulateNetworkConditions", {
    offline: false,
    latency: 400,
    downloadThroughput: (500 * 1024) / 8,
    uploadThroughput: (500 * 1024) / 8,
  });

  const t0 = Date.now();
  await page.goto("/stamboken/arsrapport/M9002/2025");
  await expect(rows(page)).toHaveCount(6);
  await hydrated(page);
  test.info().annotations.push({
    type: "sekunder till användbar sida",
    description: String((Date.now() - t0) / 1000),
  });
  await checkScroll();

  const first = rabbit(page, "M9002-2411");
  await kvar(first).check();
  await weight(first).fill("72");
  await expect(page.getByText("Menade du 7,2 kg?")).toBeVisible();
  await shot(page, "typ-b-grammhint");
  await page.getByRole("button", { name: "Ja, 7,2 kg" }).click();
  await expect(weight(first)).toHaveValue("7,2");
  const second = rabbit(page, "M9002-2412");
  await kvar(second).check();
  await weight(second).fill("2,9");

  // The autosave has reached the server: the draft holds both weights.
  await expect
    .poll(
      async () => {
        const draft = JSON.stringify(
          (await storedReport(page, "M9002")).draft?.data ?? {},
        );
        return draft.includes('"7,2"') && draft.includes('"2,9"');
      },
      { timeout: 30_000 },
    )
    .toBe(true);
  await page.reload();
  await expect(rows(page)).toHaveCount(6);
  await hydrated(page);
  await expect(kvar(rabbit(page, "M9002-2411"))).toBeChecked();
  await expect(weight(rabbit(page, "M9002-2411"))).toHaveValue("7,2");
  await expect(kvar(rabbit(page, "M9002-2412"))).toBeChecked();
  await expect(weight(rabbit(page, "M9002-2412"))).toHaveValue("2,9");

  for (const n of range(2413, 2415)) {
    const r = rabbit(page, `M9002-${n}`);
    await kvar(r).check();
    await weight(r).fill("2,8");
  }
  await kvar(rabbit(page, "M9002-2520")).check();
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await checkScroll();
  await shot(page, "typ-b-formular");
  await page.getByRole("button", { name: SEND }).click();
  await submitted(page);
  await checkScroll();
  await shot(page, "typ-b-kvitto");
  expect(overflow, "side scroll at 320 px (WCAG 1.4.10)").toBe(0);
});

test("5. Typ C: stor besättning med döda och sålda", async ({
  page,
  context,
}) => {
  await loginInline(page, context, USERS.owner);
  await page.goto("/stamboken/arsrapport/M9003/2025");
  await expect(rows(page)).toHaveCount(30);
  await hydrated(page);
  const r = (n: number) => rabbit(page, `M9003-${n}`);

  // 4 dead: three in October and the 2025 kit M9003-2551, first with a death in March, before its birth in May.
  for (const n of [2311, 2312, 2313]) await markDead(r(n), "10");
  await markDead(r(2551), "3");
  // 6 sold: five to a buyer outside the genebank and one to another herd of the genebank.
  const outside = [2321, 2322, 2441, 2442, 2555];
  for (const n of outside)
    await markSold(page, r(n), { outside: `Köpare ${n}` });
  await markSold(page, r(2556), { herd: "M1220" });
  // 20 stay: 17 adults with a weight, 3 kits.
  for (const n of [...range(2314, 2320), ...range(2431, 2440)]) {
    await kvar(r(n)).check();
    await weight(r(n)).fill("2,8");
  }
  for (const n of [2552, 2553, 2554]) await kvar(r(n)).check();
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await shot(page, "typ-c-formular");

  // The wide layout (issue 75). The viewport goes back to 375 px afterwards.
  await test.step("bred skärm", async () => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await rows(page).last().scrollIntoViewIfNeeded();
    await expect(page.getByText(/av 30 klara/)).toBeInViewport();
    await expect(page.getByLabel("Hitta en kanin")).toBeInViewport();
    await expect(page.getByRole("button", { name: SEND })).toBeInViewport();

    await page.setViewportSize({ width: 1440, height: 900 });
    await r(2314).scrollIntoViewIfNeeded();
    const box = await r(2314).boundingBox();
    expect(box!.height).toBeLessThanOrEqual(80);

    // A short window: Tab from the search field reaches a filter that nothing covers.
    await page.setViewportSize({ width: 1280, height: 500 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.getByLabel("Hitta en kanin").focus();
    await page.keyboard.press("Tab");
    const unobscured = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement;
      const b = el.getBoundingClientRect();
      const hit = document.elementFromPoint(
        b.x + b.width / 2,
        b.y + b.height / 2,
      );
      return { name: el.textContent, ok: !!hit && el.contains(hit) };
    });
    expect(unobscured.name).toMatch(/^Inte klara/);
    expect(unobscured.ok).toBe(true);
    await page.setViewportSize({ width: 375, height: 812 });
  });

  await page.getByRole("button", { name: SEND }).click();
  const box = page.getByRole("alert").filter({ hasText: "inte klar" });
  await expect(box).toContainText("1 kanin är inte klar");
  await expect(box).toContainText(
    "Dödsdatumet kan inte vara före födelsen eller senare än i dag.",
  );
  await shot(page, "typ-c-fel-dodsdatum");
  await r(2551).locator('select[id^="month-"]').selectOption("6");
  await expect(box).toBeHidden();
  await page.getByRole("button", { name: SEND }).click();
  await submitted(page);
  await expect(page.getByText("Klart. Årsrapporten för M9003")).toBeVisible();
  await shot(page, "typ-c-kvitto");

  // Change one row after the submission and send again.
  await page.getByRole("button", { name: "Ändra", exact: true }).click();
  await weight(r(2314)).fill("3,1");
  await page.getByRole("button", { name: SEND }).click();
  await submitted(page);
  const changed = await storedReport(page, "M9003");
  expect(changed.report.revision).toBeGreaterThan(1);

  // Withdraw and send again.
  await page.getByRole("button", { name: "Dra tillbaka", exact: true }).click();
  await page.getByRole("button", { name: "Dra tillbaka rapporten" }).click();
  // The form is back and the report is gone. The "Dragen tillbaka" note is not asserted: the autosave of the row
  // changed just before can reach the server after the submit and swap the note for "Ändrad på en annan enhet".
  await expect(page.getByRole("button", { name: SEND })).toBeVisible();
  await expect(page.getByText(/^Inskickad/)).toHaveCount(0);
  expect((await storedReport(page, "M9003")).report).toBeNull();
  await shot(page, "typ-c-dragen-tillbaka");
  await expect(rows(page)).toHaveCount(30);
  // shortcut: this asserts today's behaviour, which contradicts the withdraw text ("Det du fyllt i finns kvar"):
  // a buyer outside the genebank is not kept in a draft (the buyer-data rule), so the withdrawn form has five
  // sales without a buyer and Skicka refuses them. Open for Jonas 2026-11-15; update this step when it is decided.
  await page.getByRole("button", { name: SEND }).click();
  await expect(box).toContainText("5 kaniner är inte klara");
  await expect(box).toContainText("Skriv köparens namn och ort.");
  await shot(page, "typ-c-kopare-saknas");
  for (const n of outside) {
    await r(n).getByRole("button", { name: "Ändra", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await dialog.getByLabel("Köparens namn").fill(`Köpare ${n}`);
    await dialog.getByLabel("Köparens ort").fill("Mellerud");
    await dialog.getByRole("button", { name: "Spara försäljningen" }).click();
    await expect(dialog).toBeHidden();
  }
  await page.getByRole("button", { name: SEND }).click();
  await submitted(page);
  await shot(page, "typ-c-kvitto-igen");
});

test("6. Typ D: avslutar besättningen", async ({ page, context }) => {
  await loginInline(page, context, USERS.owner);
  await page.goto("/stamboken/arsrapport/M9004/2025");
  await expect(rows(page)).toHaveCount(3);
  await hydrated(page);
  await page
    .getByRole("checkbox", { name: "Jag avslutar min genbank" })
    .check();
  await page
    .getByRole("radio", {
      name: "Jag vill vara kvar i föreningen som medlem utan genbank",
    })
    .check();
  await shot(page, "typ-d-formular");
  await page.getByRole("button", { name: SEND }).click();
  await submitted(page);
  await shot(page, "typ-d-kvitto");
});

test("7. Typ E: pappersblankett som hjälparen matar in", async ({
  page,
  context,
}) => {
  await loginInline(page, context, USERS.helper);
  await takeItem(page, "M9005");

  // The page reads no phone number from the register: the field is empty and the number is nowhere on it.
  await expect(page.locator("body")).not.toContainText("0700000005");
  for (const [k, n] of range(2411, 2415).entries())
    await enterPaperRow(page, "M9005", k, n, "2,8");
  await enterPaperRow(page, "M9005", 5, 2520, null);
  await expect(page.getByText("6 inmatade, 0 kvar")).toBeVisible();

  await page
    .getByRole("radiogroup", { name: "Publicering i Koharen" })
    .getByLabel("Nej", { exact: true })
    .check();
  await expect(page.getByLabel("Telefon", { exact: true })).toHaveValue("");
  await page.getByLabel("Telefon", { exact: true }).fill("0700000555");
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await shot(page, "typ-e-inmatning");
  await page.getByRole("button", { name: "Skicka och nästa blankett" }).click();
  await submitted(page);
  await expect(page.getByText(/Sparat i matrikeln: .*telefon/)).toBeVisible();
  await shot(page, "typ-e-kvitto");
});

test("8. Typ F: rapporterad både digitalt och på papper", async ({
  page,
  context,
}) => {
  await loginInline(page, context, USERS.owner);
  await reportAllKvar(page, "M9006");

  // Spec 5.5 (Blankett efter digital rapport): the form says "redan rapporterad den ..." and the helper
  // archives the form, or changes the report with a reason. M9006 sent two forms: one is archived, one changes.
  await loginInline(page, context, USERS.helper);
  await takeItem(page, "M9006");
  await expect(page.getByText(/^Redan rapporterad den /)).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Ändra rapporten" }),
  ).toBeDisabled();
  await page.getByLabel("Varför ändras rapporten?").fill("Pappret skiljer sig");
  await expect(
    page.getByRole("button", { name: "Ändra rapporten" }),
  ).toBeEnabled();
  await page.getByLabel("Varför ändras rapporten?").fill("");
  await shot(page, "typ-f-redan-rapporterad");
  await page.getByRole("button", { name: "Arkivera blanketten" }).click();
  await page.waitForURL(/\/stamboken\/inkorg/);
  await expect(
    page.getByText("Blanketten för M9006 är arkiverad."),
  ).toBeVisible();
  await expect(row(page, "M9006")).toHaveCount(1); // the second form
  // The digital report stands.
  await loginInline(page, context, USERS.manager);
  expect((await storedReport(page, "M9006")).report.revision).toBe(1);

  // The second form says something else: 2415 died in October. The helper changes the report with a reason.
  await loginInline(page, context, USERS.helper);
  await takeItem(page, "M9006");
  await page.getByLabel("Varför ändras rapporten?").fill("Pappret skiljer sig");
  await page.getByRole("button", { name: "Ändra rapporten" }).click();
  await expect(rows(page).first()).toBeVisible();
  await hydrated(page);
  // The rows of the digital report are filled in; the paper differs on one rabbit.
  await markDead(rabbit(page, "M9006-2415"), "10");
  await shot(page, "typ-f-andra-rapporten");
  await page.getByRole("button", { name: "Skicka och nästa blankett" }).click();
  await page.waitForURL(/\/stamboken\/inkorg/);
  await expect(
    page.getByText("M9006 inskickad: 5 finns kvar, 1 död."),
  ).toBeVisible();

  await loginInline(page, context, USERS.manager);
  const changed = await storedReport(page, "M9006");
  expect(changed.report.revision).toBe(2);
  const suffix = (id: string) =>
    changed.rabbits.find((r: { id: number }) => r.id === Number(id)).number;
  const entries = Object.fromEntries(
    Object.entries(changed.report.submitted.rabbits).map(([id, e]) => [
      suffix(id),
      e,
    ]),
  );
  expect(entries["M9006-2415"]).toMatchObject({
    val: "dod",
    dod: { ar: 2025, manad: 10 },
  });
  const rabbit2415 = await page.request.get(
    `${API_URL}/api/v2/individual/M9006-2415`,
  );
  expect((await rabbit2415.json()).death_date).toMatch(/^2025-10-/);
});

test("9. Typ G: död och försäljning vid årsskiftet", async ({
  page,
  context,
}) => {
  const villkor = async () =>
    (await storedReport(page, "M9007")).report.villkor;
  // Alive on 31 December is an ATTESTATION on that day, which the report view shows as last_reported.
  const alive = async () =>
    (await storedReport(page, "M9007")).rabbits
      .filter(
        (r: { last_reported: string | null }) =>
          r.last_reported === "2025-12-31",
      )
      .map((r: { number: string }) => r.number);
  await loginInline(page, context, USERS.owner);
  await page.goto("/stamboken/arsrapport/M9007/2025");
  await expect(rows(page)).toHaveCount(2);
  await hydrated(page);
  const male = rabbit(page, "M9007-2411");
  const female = rabbit(page, "M9007-2412");

  // a) Both leave on 1 January 2026: they lived on 31 December, so the herd has a male and a female.
  await male.getByRole("radio", { name: "Död", exact: true }).check();
  await male.getByLabel("År").selectOption("2026");
  await male.locator('select[id^="month-"]').selectOption("1");
  await male.getByLabel("Dag (frivillig)").fill("1");
  await markSold(
    page,
    female,
    { herd: "M9001" },
    { ar: "2026", manad: "1", dag: "1" },
  );
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await shot(page, "typ-g-formular");
  await page.getByRole("button", { name: SEND }).click();
  await submitted(page);
  await loginInline(page, context, USERS.manager);
  expect(await villkor()).toMatchObject({ hane: true, hona: true });
  expect(await alive()).toEqual(["M9007-2411", "M9007-2412"]);

  // b) The same on 31 December 2025: both were gone on 31 December.
  await loginInline(page, context, USERS.owner);
  await page.goto("/stamboken/arsrapport/M9007/2025");
  await page.getByRole("button", { name: "Ändra", exact: true }).click();
  await male.getByLabel("År").selectOption("2025");
  await male.locator('select[id^="month-"]').selectOption("12");
  await male.getByLabel("Dag (frivillig)").fill("31");
  await female.getByRole("button", { name: "Ändra", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("År").selectOption("2025");
  await dialog.getByLabel("Månad").selectOption("12");
  await dialog.getByLabel("Dag (frivillig)").fill("31");
  await dialog.getByRole("button", { name: "Spara försäljningen" }).click();
  await expect(dialog).toBeHidden();
  await shot(page, "typ-g-andrad");
  await page.getByRole("button", { name: SEND }).click();
  await submitted(page);
  await loginInline(page, context, USERS.manager);
  expect(await villkor()).toMatchObject({ hane: false, hona: false });
  expect(await alive()).toEqual([]);
});

test("10. Paritet: samma svar på papper och digitalt ger samma data", async ({
  page,
  context,
}) => {
  const weights: Record<number, string> = {
    2411: "2,8",
    2412: "3,1",
    2413: "2,9",
    2414: "3,0",
  };

  await loginInline(page, context, USERS.owner);
  await page.goto("/stamboken/arsrapport/M9101/2025");
  await expect(rows(page)).toHaveCount(6);
  await hydrated(page);
  for (const [n, w] of Object.entries(weights)) {
    const r = rabbit(page, `M9101-${n}`);
    await kvar(r).check();
    await weight(r).fill(w);
  }
  await markDead(rabbit(page, "M9101-2415"), "10");
  await kvar(rabbit(page, "M9101-2520")).check();
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await page.getByRole("button", { name: SEND }).click();
  await submitted(page);

  await loginInline(page, context, USERS.helper);
  await takeItem(page, "M9102");
  const order = [2415, 2411, 2412, 2413, 2414, 2520];
  for (const [k, n] of order.entries()) {
    const number = page.getByLabel("Nummer efter M9102-");
    await number.fill(String(n));
    await number.press("Enter");
    const r = rows(page).nth(k);
    if (n === 2415) await markDead(r, "10");
    else {
      await kvar(r).check();
      if (weights[n]) await weight(r).fill(weights[n]);
    }
  }
  await page.getByRole("radio", { name: NO_DISEASE }).check();
  await shot(page, "paritet-papper");
  await page.getByRole("button", { name: "Skicka och nästa blankett" }).click();
  await page.waitForURL(/\/stamboken\/inkorg/);

  await expect(
    page.getByText("M9102 inskickad: 5 finns kvar, 1 död."),
  ).toBeVisible();

  // Both stored reports, read as the manager. Dropped before the comparison, because they differ by design or by
  // the moment: ids (report, rabbits, inbox item), `received_at` and `report_date` (the day the form came in on
  // paper, the minute of the submit digitally), `source` and `inbox_item_id` (the channel), `received_on` and
  // `signed_on` (paper only), `withdraw_until`, and the herd code, which is cut from each rabbit's number.
  await loginInline(page, context, USERS.manager);
  const normalise = (
    herd: string,
    view: Awaited<ReturnType<typeof storedReport>>,
  ) => {
    type Rabbit = {
      id: number;
      number: string;
      state: string;
      death_date: string | null;
      last_reported: string | null;
    };
    const rabbits: Rabbit[] = view.rabbits;
    const suffix = (id: string) =>
      rabbits.find((r) => r.id === Number(id))!.number.replace(`${herd}-`, "");
    const {
      submitted,
      villkor,
      on_time,
      revision,
      status,
      can_change,
      can_withdraw,
    } = view.report;
    const {
      rabbits: entries,
      inbox_item_id,
      received_on,
      signed_on,
      ...body
    } = submitted;
    void [inbox_item_id, received_on, signed_on];
    return {
      report: { villkor, on_time, revision, status, can_change, can_withdraw },
      body,
      entries: Object.fromEntries(
        Object.entries(entries).map(([id, e]) => [suffix(id), e]),
      ),
      // what the report did to the register
      register: Object.fromEntries(
        rabbits.map((r) => [
          r.number.replace(`${herd}-`, ""),
          {
            state: r.state,
            death_date: r.death_date,
            last_reported: r.last_reported,
          },
        ]),
      ),
    };
  };
  // The register itself, per rabbit: the report's view hides a death before year-end (death_date is null for
  // both "none" and "before 31 December"), so the individual's own record is read, with its stored weights.
  const individuals = async (herd: string) =>
    Object.fromEntries(
      await Promise.all(
        [...range(2411, 2415), 2520].map(async (n) => {
          const res = await page.request.get(
            `${API_URL}/api/v2/individual/${herd}-${n}`,
          );
          expect(res.ok()).toBe(true);
          const { death_date, weights } = await res.json();
          return [String(n), { death_date, weights }];
        }),
      ),
    );
  const digital = {
    ...normalise("M9101", await storedReport(page, "M9101")),
    individuals: await individuals("M9101"),
  };
  const paper = {
    ...normalise("M9102", await storedReport(page, "M9102")),
    individuals: await individuals("M9102"),
  };
  // Equal is not enough: both channels could miss the same attestation. The five that stay are alive on 31
  // December in the register (an ATTESTATION that day, shown as last_reported), and the dead one is not.
  for (const view of [digital, paper]) {
    for (const n of ["2411", "2412", "2413", "2414", "2520"])
      expect(view.register[n].last_reported).toBe("2025-12-31");
    expect(view.register["2415"].last_reported).not.toBe("2025-12-31");
  }
  // Rabbit 2415 is dead in the register, in October 2025, in both herds.
  expect(digital.individuals["2415"].death_date).toMatch(/^2025-10-/);
  expect(paper.individuals["2415"].death_date).toMatch(/^2025-10-/);
  expect(digital.individuals["2412"].weights).toHaveLength(1);
  expect(Object.keys(digital.entries)).toHaveLength(6);
  expect(digital.entries["2415"]).toMatchObject({
    val: "dod",
    dod: { ar: 2025, manad: 10 },
  });
  expect(paper).toEqual(digital);
});

test("11. Genbanksansvarig ser rätt status för alla typer", async ({
  page,
  context,
}) => {
  await loginInline(page, context, USERS.manager);
  await page.goto("/stamboken/arsrapport/status/2025");
  for (const herd of [
    "M9001",
    "M9002",
    "M9003",
    "M9005",
    "M9006",
    "M9007",
    "M9101",
    "M9102",
  ])
    await expect(row(page, herd)).toContainText("Inskickad");
  for (const herd of ["M9001", "M9002", "M9003", "M9007", "M9101"])
    await expect(row(page, herd)).toContainText("inloggad");
  // M9006 was reported digitally and then changed from its second paper form: its report is now a paper one.
  for (const herd of ["M9005", "M9006", "M9102"])
    await expect(row(page, herd)).toContainText(/Inskickad\s*blankett/);
  await expect(row(page, "M9004")).toContainText("Avslutar");
  await expect(row(page, "M9004")).toContainText("Medlemskapet består");
  await shot(page, "status-efter-rapporter");

  await page.goto("/stamboken/arsrapport/status/2025?filter=att_ringa");
  await expect(page.getByText("Inga besättningar att ringa.")).toBeVisible();
});
