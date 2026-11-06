import { test, expect, type Page } from "@playwright/test";

// Seed data (flask seed create), genebank 1:
//   G1274-2112 "Visby Vilda"  (female, inactive) — parents G1274-1911 + G1274-1921
//   G1274-2111 "Visby Viking" (male, inactive)   — Vilda's full brother -> F 25 %
//   G1274-2116 "Visby Storm"  (male, active)     — unrelated            -> F 0 %
// Auth is handled by storageState (gk-owner) set in playwright.config.ts.
// Read-only: the calculation endpoint writes nothing.

const SHARED_URL =
  "/stamboken/provparning?genebank=1&hona=G1274-2112&hane=G1274-2111&hane=G1274-2116";

async function pick(page: Page, label: string, search: string, option: RegExp) {
  const input = page.getByRole("combobox", { name: label, exact: true });
  await input.click();
  await input.fill(search);
  await page.getByRole("option", { name: option }).click();
}

const cards = (page: Page) => page.getByTestId("result-card");

const SHARED_HANE = ["G1274-2111", "G1274-2116"];

// The males in the browser's URL right now (page.url() lags replaceState).
const search = (page: Page) =>
  page.evaluate(() => new URLSearchParams(location.search).getAll("hane"));

// A client-side navigation on the same route (what a link or "Provpara" does).
const push = (page: Page, url: string) =>
  page.evaluate(
    (u) =>
      (
        window as unknown as {
          next: { router: { push: (url: string) => void } };
        }
      ).next.router.push(u),
    url,
  );

test.describe("Provparning", () => {
  test("empty state asks for a female and a male", async ({ page }) => {
    await page.goto("/stamboken/provparning");
    await expect(page.getByText("Välj en hona och minst en hane")).toBeVisible({
      timeout: 15000,
    });
    await expect(cards(page)).toHaveCount(0);
  });

  test("female + two males gives two cards sorted by F, URL mirrors the choice", async ({
    page,
  }) => {
    await page.goto("/stamboken/provparning");

    // Dead/inactive animals are searchable (Vilda is inactive)
    await pick(page, "Hona", "Vilda", /Visby Vilda.*G1274-2112/);
    await pick(page, "Hane", "Viking", /Visby Viking.*G1274-2111/);
    await page.getByRole("button", { name: "Lägg till en hane till" }).click();
    await pick(page, "Hane 2", "Storm", /Visby Storm.*G1274-2116/);

    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });

    // Sorted by F ascending: Storm (0 %) before Viking (25 %), though Viking
    // was picked first.
    await expect(cards(page).nth(0)).toContainText("G1274-2116");
    await expect(cards(page).nth(0).getByTestId("offspring-f")).toHaveText(
      /^0,0\s%$/,
    );
    await expect(cards(page).nth(0).getByTestId("verdict")).toHaveAttribute(
      "data-verdict",
      "good",
    );
    await expect(cards(page).nth(1)).toContainText("G1274-2111");
    await expect(cards(page).nth(1).getByTestId("offspring-f")).toHaveText(
      /^25,0\s%$/,
    );
    await expect(cards(page).nth(1).getByTestId("verdict")).toHaveAttribute(
      "data-verdict",
      "high",
    );
    // Colour is never alone: text + icon in the badge, and a close-kin warning
    await expect(cards(page).nth(1).getByTestId("verdict")).toContainText(
      "Hög inavel",
    );
    await expect(
      cards(page).nth(1).getByTestId("relation-warning"),
    ).toContainText("helsyskon");
    await expect(
      cards(page).nth(0).getByTestId("relation-warning"),
    ).toHaveCount(0);

    // Common ancestors are listed with number + name
    const ancestors = cards(page).nth(1).getByTestId("common-ancestors");
    await expect(ancestors).toContainText("G1274-1911");
    await expect(ancestors).toContainText("Visby Stamfar");
    await expect(ancestors).toContainText("G1274-1921");

    // URL mirrors the registered selection (replace, repeated hane)
    await expect
      .poll(() => new URL(page.url()).searchParams.get("hona"))
      .toBe("G1274-2112");
    const params = new URL(page.url()).searchParams;
    expect(params.get("genebank")).toBe("1");
    expect(params.getAll("hane")).toEqual(["G1274-2111", "G1274-2116"]);
  });

  test("a shared URL opens with the same selection and result", async ({
    page,
  }) => {
    await page.goto(SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    await expect(cards(page).nth(0)).toContainText("G1274-2116");
    await expect(cards(page).nth(1)).toContainText("G1274-2111");
    await expect(
      page.getByRole("combobox", { name: "Hona", exact: true }),
    ).toHaveValue(/G1274-2112/);
    await expect(
      page.getByRole("combobox", { name: "Hane", exact: true }),
    ).toHaveValue(/G1274-2111/);
    await expect(
      page.getByRole("combobox", { name: "Hane 2", exact: true }),
    ).toHaveValue(/G1274-2116/);
  });

  test("an unregistered female is described by her parents", async ({
    page,
  }) => {
    await page.goto("/stamboken/provparning?genebank=1&hane=G1274-2111");
    await page
      .getByRole("button", { name: "Honan är inte registrerad än" })
      .click();
    await pick(page, "Hona – mor", "Stammor", /Visby Stammor.*G1274-1921/);
    await pick(page, "Hona – far", "Stamfar", /Visby Stamfar.*G1274-1911/);

    // A full sister of Viking that is not registered yet
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    await expect(cards(page).first().getByTestId("offspring-f")).toHaveText(
      /^25,0\s%$/,
    );
    await expect(
      cards(page).first().getByTestId("relation-warning"),
    ).toContainText("helsyskon");
    await expect(page.getByTestId("female-summary")).toContainText(
      "Oregistrerad hona",
    );
  });

  test("the pedigree tree unfolds and marks common ancestors", async ({
    page,
  }) => {
    await page.goto(SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });

    const viking = cards(page).nth(1);
    await viking.getByRole("button", { name: "Visa släktträd" }).click();
    const tree = viking.getByTestId("pedigree-tree");
    await expect(tree).toBeVisible({ timeout: 15000 });
    // Female (Vilda) on top, male (Viking) below, grandparents shared
    await expect(tree.getByText("G1274-2112")).toBeVisible();
    await expect(tree.getByText("G1274-2111")).toBeVisible();
    // Marked with text, not colour alone: Stamfar + Stammor on both sides
    await expect(tree.getByTestId("pedigree-common-ancestor")).toHaveCount(4);
    await expect(
      tree.getByTestId("pedigree-common-ancestor").first(),
    ).toHaveText("gemensam");
  });

  test("375px: no horizontal page scroll with the tree expanded", async ({
    page,
  }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    await cards(page)
      .nth(1)
      .getByRole("button", { name: "Visa släktträd" })
      .click();
    const tree = page.getByTestId("pedigree-tree");
    await expect(tree).toBeVisible({ timeout: 15000 });
    // Stacked layout below 640 px: the tree itself needs no horizontal scroll
    await expect(tree).toHaveAttribute("data-layout", "stacked");
    await expect(tree.getByTestId("pedigree-common-ancestor")).toHaveCount(4);
    const treeOverflow = await tree.evaluate(
      (el) => el.scrollWidth - el.clientWidth,
    );
    expect(treeOverflow).toBeLessThanOrEqual(0);

    const overflow = await page.evaluate(
      () =>
        document.documentElement.scrollWidth -
        document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });

  test("a query-only client navigation replaces the selection", async ({
    page,
  }) => {
    await page.goto(SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    // Same route, new query (what "Provpara" from an individual page or the
    // back button does): the form must follow the URL, not keep its old state.
    await push(
      page,
      "/stamboken/provparning?genebank=1&hona=G1274-2112&hane=G1274-2116",
    );
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    await expect(cards(page).first()).toContainText("G1274-2116");
    await expect(
      page.getByRole("combobox", { name: "Hane", exact: true }),
    ).toHaveValue(/G1274-2116/);
  });

  test("navigating back to the opening selection after editing it restores that selection (A -> B -> A)", async ({
    page,
  }) => {
    // A: two males, opened from the URL.
    await page.goto(SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    // B: edit in the form (history.replaceState only, no server round trip).
    await page.getByRole("button", { name: "Ta bort hane 2" }).click();
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    await expect
      .poll(() => new URL(page.url()).searchParams.getAll("hane"))
      .toEqual(["G1274-2111"]);
    // A again, by client navigation: the server-resolved selection is
    // identical to the one the page opened with, so only the URL tells.
    await push(page, SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    await expect(
      page.getByRole("combobox", { name: "Hane 2", exact: true }),
    ).toHaveValue(/G1274-2116/);
    expect(new URL(page.url()).searchParams.getAll("hane")).toEqual([
      "G1274-2111",
      "G1274-2116",
    ]);
  });

  test("edits C -> B -> C -> B, then a client navigation to C shows C", async ({
    page,
  }) => {
    const hane = () => new URL(page.url()).searchParams.getAll("hane");
    // C: Viking + Storm, opened from the URL.
    await page.goto(SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    // B
    await page.getByRole("button", { name: "Ta bort hane 2" }).click();
    await expect.poll(hane).toEqual(["G1274-2111"]);
    // C again, by editing
    await page.getByRole("button", { name: "Lägg till en hane till" }).click();
    await pick(page, "Hane 2", "Storm", /Visby Storm.*G1274-2116/);
    await expect.poll(hane).toEqual(["G1274-2111", "G1274-2116"]);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    // B again
    await page.getByRole("button", { name: "Ta bort hane 2" }).click();
    await expect.poll(hane).toEqual(["G1274-2111"]);
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    // C by navigation (may be served from the router cache)
    await push(page, SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    await expect(
      page.getByRole("combobox", { name: "Hane 2", exact: true }),
    ).toHaveValue(/G1274-2116/);
    expect(hane()).toEqual(["G1274-2111", "G1274-2116"]);
  });

  test("rapid edits end in the state the URL holds", async ({ page }) => {
    await page.goto("/stamboken/provparning?genebank=1&hona=G1274-2112");
    // Two males in quick succession, no waiting for results in between.
    await pick(page, "Hane", "Viking", /Visby Viking.*G1274-2111/);
    await page.getByRole("button", { name: "Lägg till en hane till" }).click();
    await pick(page, "Hane 2", "Storm", /Visby Storm.*G1274-2116/);
    // Remove both in the same task: the second click runs before React (or
    // the router) has rendered the first, so it must start from the URL the
    // first one wrote — not from what is on screen.
    await page.evaluate(() => {
      const button = (label: string) =>
        document.querySelector<HTMLButtonElement>(
          `button[aria-label="${label}"]`,
        )!;
      const first = button("Ta bort hane");
      const second = button("Ta bort hane 2");
      first.click();
      second.click();
    });
    await expect
      .poll(() => new URL(page.url()).searchParams.getAll("hane"))
      .toEqual([]);
    const males = page.getByRole("combobox", { name: /^Hane( \d+)?$/ });
    await expect(males).toHaveCount(1);
    await expect(males).toHaveValue("");
    await expect(cards(page)).toHaveCount(0);
    await expect(
      page.getByText("Välj en hona och minst en hane"),
    ).toBeVisible();
    // The female was not touched.
    await expect(
      page.getByRole("combobox", { name: "Hona", exact: true }),
    ).toHaveValue(/G1274-2112/);
    expect(new URL(page.url()).searchParams.get("hona")).toBe("G1274-2112");
  });

  test("back and forward between two provparning entries follow the URL", async ({
    page,
  }) => {
    // A: "Provpara" from Vilda's individual page.
    await page.goto("/stamboken/individ/G1274-2112");
    await page.getByRole("button", { name: "Fler åtgärder" }).click();
    await page.getByRole("menuitem", { name: "Provpara" }).click();
    await page.waitForURL(/\/stamboken\/provparning\?/);
    const female = page.getByRole("combobox", { name: "Hona", exact: true });
    await expect(female).toHaveValue(/G1274-2112/, { timeout: 15000 });
    const urlA = page.url();
    // X: another selection, pushed on the same route.
    await push(page, SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    // Back to A: Vilda alone, no males, no results.
    await page.goBack();
    await expect.poll(() => page.url()).toBe(urlA);
    await expect(cards(page)).toHaveCount(0);
    await expect(female).toHaveValue(/G1274-2112/);
    await expect(
      page.getByRole("combobox", { name: "Hane", exact: true }),
    ).toHaveValue("");
    await expect(
      page.getByRole("combobox", { name: "Hane 2", exact: true }),
    ).toHaveCount(0);
    // Forward to X again.
    await page.goForward();
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    await expect(
      page.getByRole("combobox", { name: "Hane 2", exact: true }),
    ).toHaveValue(/G1274-2116/);
  });

  test("an unregistered male stays through registered edits", async ({
    page,
  }) => {
    await page.goto(
      "/stamboken/provparning?genebank=1&hona=G1274-2112&hane=G1274-2116",
    );
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    await page.getByRole("button", { name: "Lägg till en hane till" }).click();
    const second = page.getByTestId("picker-male-2");
    await second
      .getByRole("button", { name: "Hanen är inte registrerad än" })
      .click();
    await pick(page, "Hane 2 – far", "Stamfar", /Visby Stamfar.*G1274-1911/);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    // Not in the URL ...
    expect(new URL(page.url()).searchParams.getAll("hane")).toEqual([
      "G1274-2116",
    ]);
    // ... and kept when the registered male changes.
    await pick(page, "Hane", "Viking", /Visby Viking.*G1274-2111/);
    await expect
      .poll(() => new URL(page.url()).searchParams.getAll("hane"))
      .toEqual(["G1274-2111"]);
    await expect(
      page.getByRole("combobox", { name: "Hane 2 – far", exact: true }),
    ).toHaveValue(/G1274-1911/);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    await expect(
      cards(page).filter({ hasText: "Oregistrerad hane (far G1274-1911)" }),
    ).toHaveCount(1);
  });

  test("picking the same male again keeps him", async ({ page }) => {
    await page.goto(SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    // The prefilled Viking and the search hit are different objects.
    await pick(page, "Hane", "Viking", /Visby Viking.*G1274-2111/);
    // replaceState is synchronous: the URL is final once the click returns.
    expect(await search(page)).toEqual(SHARED_HANE);
    await expect(
      page.getByRole("combobox", { name: "Hane", exact: true }),
    ).toHaveValue(/G1274-2111/);
    await expect(cards(page)).toHaveCount(2);
  });

  test("two picks in the same slot in one task: the last one wins", async ({
    page,
  }) => {
    await page.goto(
      "/stamboken/provparning?genebank=1&hona=G1274-2112&hane=G1274-2116",
    );
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    const input = page.getByRole("combobox", { name: "Hane", exact: true });
    await input.click();
    await input.fill("Visby");
    await expect(
      page.getByRole("option", { name: /G1274-2111/ }),
    ).toBeVisible();
    await expect(
      page.getByRole("option", { name: /G1274-1911/ }),
    ).toBeVisible();
    // Viking, then Stamfar, before React or the router render the first.
    await page.evaluate(() => {
      const option = (n: string) =>
        [...document.querySelectorAll<HTMLElement>('[role="option"]')].find(
          (o) => o.textContent?.includes(n),
        )!;
      const viking = option("G1274-2111");
      const stamfar = option("G1274-1911");
      viking.click();
      stamfar.click();
    });
    expect(await search(page)).toEqual(["G1274-1911"]);
    await expect(input).toHaveValue(/G1274-1911/);
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    await expect(cards(page).first()).toContainText("G1274-1911");
  });

  test("an old pre-edit layout never comes back on a later navigation", async ({
    page,
  }) => {
    const url =
      "/stamboken/provparning?genebank=1&hona=G1274-2112&hane=G1274-2116";
    await page.goto(url);
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    const picker = page.getByTestId("picker-male-1");
    // Storm -> unregistered with a father -> Storm -> unregistered again.
    await picker
      .getByRole("button", { name: "Hanen är inte registrerad än" })
      .click();
    await pick(page, "Hane – far", "Stamfar", /Visby Stamfar.*G1274-1911/);
    await picker
      .getByRole("button", { name: "Välj ur stamboken i stället" })
      .click();
    await expect.poll(() => search(page)).toEqual(["G1274-2116"]);
    await picker
      .getByRole("button", { name: "Hanen är inte registrerad än" })
      .click();
    await expect.poll(() => search(page)).toEqual([]);
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    await expect(page.getByTestId("female-summary")).toBeVisible();
    // Navigating to the URL the form had before its last edit: the
    // unregistered male stays, Storm is added next to him.
    await push(page, url);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    await expect(
      page.getByRole("combobox", { name: "Hane – far", exact: true }),
    ).toHaveValue(/G1274-1911/);
    await expect(
      page.getByRole("combobox", { name: "Hane 2", exact: true }),
    ).toHaveValue(/G1274-2116/);
  });

  test("more than ten males after a navigation: a message instead of a calculation", async ({
    page,
  }) => {
    const ten = [
      "G1274-1911",
      "G1274-2011",
      "G1274-2055",
      "G1274-2065",
      "G1274-2111",
      "G1274-2116",
      "G1274-2118",
      "G1274-2151",
      "G1274-2161",
      "G1274-2171",
    ];
    const sent: number[] = [];
    page.on("request", (req) => {
      if (req.method() === "POST" && req.url().includes("/v2/testbreed"))
        sent.push((req.postDataJSON() as { males: unknown[] }).males.length);
    });
    await page.goto(
      "/stamboken/provparning?genebank=1&hona=G1274-2112&hane=G1274-2116",
    );
    await expect(cards(page)).toHaveCount(1, { timeout: 15000 });
    // A local unregistered male ...
    await page.getByRole("button", { name: "Lägg till en hane till" }).click();
    await page
      .getByTestId("picker-male-2")
      .getByRole("button", { name: "Hanen är inte registrerad än" })
      .click();
    await pick(page, "Hane 2 – far", "Stamfar", /Visby Stamfar.*G1274-1911/);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    // ... plus ten registered ones from a link: eleven comparisons.
    await push(
      page,
      `/stamboken/provparning?genebank=1&hona=G1274-2112&${ten
        .map((n) => `hane=${n}`)
        .join("&")}`,
    );
    await expect(page.getByTestId("too-many-males")).toHaveText(
      "Högst 10 hanar åt gången — ta bort någon för att räkna.",
      { timeout: 15000 },
    );
    await expect(cards(page)).toHaveCount(0);
    // Storm keeps slot 1, the unregistered male slot 2, the rest follow.
    await expect(
      page.getByRole("combobox", { name: "Hane 11", exact: true }),
    ).toHaveValue(/G1274-2171/);
    // Removing one brings the calculation back; eleven were never sent.
    await page.getByRole("button", { name: "Ta bort hane 2" }).click();
    await expect(page.getByTestId("too-many-males")).toHaveCount(0);
    await expect(cards(page)).toHaveCount(10, { timeout: 15000 });
    expect(sent.length).toBeGreaterThan(0);
    expect(Math.max(...sent)).toBeLessThanOrEqual(10);
  });

  test("the expanded tree comes from the calculation response (no separate pedigree request)", async ({
    page,
  }) => {
    const pedigreeCalls: string[] = [];
    page.on("request", (req) => {
      if (/\/individual\/[^/]+\/pedigree/.test(req.url()))
        pedigreeCalls.push(req.url());
    });
    await page.goto(SHARED_URL);
    await expect(cards(page)).toHaveCount(2, { timeout: 15000 });
    await cards(page)
      .nth(1)
      .getByRole("button", { name: "Visa släktträd" })
      .click();
    await expect(cards(page).nth(1).getByTestId("pedigree-tree")).toBeVisible();
    expect(pedigreeCalls).toEqual([]);
  });
});
