// Spec §7.3, C8-revision: brödsmulorna är borttagna (stamboken-drift:docs/design/design_handoff_admin/
// README "Breadcrumbs are removed"). Varje icke-landningssida renderar
// i stället den klistrade flikraden (rotad i Översikt → /stamboken/admin),
// och varje sida som inte är en flikdestination har en "← …"-tillbakalänk.
// The post-mutation redirect-to-list half of this spec is asserted where the
// mutations live (05 profile edit, 11 herd edit, 12 create, 13 gb name).
import { test, expect } from "@playwright/test";
import { loginAs, ADMIN } from "./helpers/auth";
import {
  BACK_TO_GENEBANKS,
  BACK_TO_HERDS,
  BACK_TO_SYSTEM,
  BACK_TO_USERS,
  TAB_NAV_LABEL,
  TAB_OVERVIEW,
} from "./helpers/copy";

const PAGES = [
  "/stamboken/admin/anvandare",
  "/stamboken/admin/besattningar",
  "/stamboken/admin/besattningar/ny",
  "/stamboken/admin/genbanker",
  "/stamboken/admin/system",
  "/stamboken/admin/system/audit",
  "/stamboken/admin/system/online",
  "/stamboken/admin/system/synk",
  "/stamboken/admin/system/ratelimit",
];

// Undersidor som inte är flikdestinationer → tillbakalänk till sin sektion.
// Detaljsidorna med id (anvandare/[userId], besattningar/[herdId],
// genbanker/[gbId]) har ingen stabil URL att hårdkoda — de nås via
// klick-genom från sina listor i det tredje testet nedan.
const BACK_LINKS: [string, RegExp, RegExp][] = [
  [
    "/stamboken/admin/besattningar/ny",
    BACK_TO_HERDS,
    /\/stamboken\/admin\/besattningar$/,
  ],
  [
    "/stamboken/admin/system/audit",
    BACK_TO_SYSTEM,
    /\/stamboken\/admin\/system$/,
  ],
  [
    "/stamboken/admin/system/online",
    BACK_TO_SYSTEM,
    /\/stamboken\/admin\/system$/,
  ],
  [
    "/stamboken/admin/system/synk",
    BACK_TO_SYSTEM,
    /\/stamboken\/admin\/system$/,
  ],
  [
    "/stamboken/admin/system/ratelimit",
    BACK_TO_SYSTEM,
    /\/stamboken\/admin\/system$/,
  ],
];

test.beforeEach(async ({ page, context }) => {
  await loginAs(page, context, ADMIN, "prod");
});

test("every non-landing page renders the admin tab row rooted at Översikt", async ({
  page,
}) => {
  for (const path of PAGES) {
    await page.goto(path);
    // C8:s AdminTabs renderar nav[aria-label="Adminpanelens avsnitt"].
    const tabs = page.locator(`nav[aria-label="${TAB_NAV_LABEL}"]`);
    await expect(tabs, `${path} must render the admin tab row`).toBeVisible();
    // role="tab", inte "link" — flikarna sätter role explicit (som TabBar).
    const overview = tabs.getByRole("tab", { name: TAB_OVERVIEW, exact: true });
    await expect(overview, `${path} Översikt tab`).toBeVisible();
    await expect(overview).toHaveAttribute("href", /\/stamboken\/admin\/?$/);
  }
});

test("sub-pages render a back link to their section", async ({ page }) => {
  for (const [path, name, href] of BACK_LINKS) {
    await page.goto(path);
    const back = page.getByRole("link", { name });
    await expect(back, `${path} must have a back link`).toBeVisible();
    await expect(back).toHaveAttribute("href", href);
  }
});

test("detail pages render a back link to their list", async ({ page }) => {
  // Användare: klick-genom via admins egen radlänk (stabil fixtur).
  await page.goto("/stamboken/admin/anvandare");
  await page.getByRole("link", { name: ADMIN.username, exact: true }).click();
  const backUsers = page.getByRole("link", { name: BACK_TO_USERS });
  await expect(backUsers).toBeVisible();
  await expect(backUsers).toHaveAttribute(
    "href",
    /\/stamboken\/admin\/anvandare$/,
  );

  // Besättning: första radlänken (koden är en riktig <a> före och efter C13).
  await page.goto("/stamboken/admin/besattningar");
  await page.getByRole("link", { name: /^G\d+/ }).first().click();
  const backHerds = page.getByRole("link", { name: BACK_TO_HERDS });
  await expect(backHerds).toBeVisible();
  await expect(backHerds).toHaveAttribute(
    "href",
    /\/stamboken\/admin\/besattningar$/,
  );

  // Genbank: id 1 är hårdkodad i filtret (besattningar/page.tsx) och stabil.
  await page.goto("/stamboken/admin/genbanker/1");
  const backGb = page.getByRole("link", { name: BACK_TO_GENEBANKS });
  await expect(backGb).toBeVisible();
  await expect(backGb).toHaveAttribute(
    "href",
    /\/stamboken\/admin\/genbanker$/,
  );
});
