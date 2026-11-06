import { test, expect, type Page, type BrowserContext } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Skärmbilder till användarmanualen. Varje post ger två filer i docs/manual/:
// <namn>-mobil.png (375 px) och <namn>-desktop.png (1280 px). Kräver att
// mutation-manual-flows.spec.ts körts först (kull med kullista, utfärdat intyg)
// och att MANUAL_CERT_UUID pekar på ett utfärdat intyg (annars hoppas den bilden).

const OUT = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../docs/manual",
);
const USERS = {
  owner: { username: "test-gk-owner", password: "test-gk-owner-pass" },
  manager: { username: "test-gk-manager", password: "test-gk-pass" },
  admin: { username: "test-admin", password: "test-admin-pass" },
} as const;
type Role = keyof typeof USERS | "anonymous";

type Shot = {
  name: string;
  role: Role;
  path: string;
  actions?: string[];
  fullPage?: boolean;
};

const SHOTS: Shot[] = [
  { name: "logga-in", role: "anonymous", path: "/auth/sign-in" },
  {
    name: "min-besattning-oversikt",
    role: "owner",
    path: "/stamboken/min-besattning",
    fullPage: true,
  },
  {
    name: "min-besattning-kaniner",
    role: "owner",
    path: "/stamboken/min-besattning?tab=individuals",
  },
  {
    name: "min-besattning-kullar",
    role: "owner",
    path: "/stamboken/min-besattning?tab=breeding",
  },
  {
    name: "ny-kull",
    role: "owner",
    path: "/stamboken/min-besattning?tab=breeding",
    actions: ["click:+ Ny kull"],
  },
  {
    name: "ny-parning",
    role: "owner",
    path: "/stamboken/min-besattning?tab=breeding",
    actions: ["click:Ny parning"],
  },
  {
    name: "kullista",
    role: "owner",
    path: "/stamboken/min-besattning?tab=breeding",
    actions: ["click:Jag vet hur det fungerar", "card:Född 2025", "wait:1500"],
  },
  {
    name: "registrera-kanin",
    role: "owner",
    path: "/stamboken/min-besattning?tab=breeding",
    actions: [
      "click:Jag vet hur det fungerar",
      "card:Född 2025",
      "wait:1500",
      "button:Registrera",
      "wait:1500",
    ],
  },
  {
    name: "min-besattning-slakttrad",
    role: "owner",
    path: "/stamboken/min-besattning?tab=pedigree",
  },
  {
    name: "besattningsuppgifter",
    role: "owner",
    path: "/stamboken/min-besattning",
    actions: ["click:Redigera", "scroll:Besättningsuppgifter"],
  },
  {
    name: "individ",
    role: "owner",
    path: "/stamboken/individ/G1274-2117",
    fullPage: true,
  },
  {
    name: "individ-fler-atgarder",
    role: "owner",
    path: "/stamboken/individ/G1274-2117",
    actions: ["click:Fler åtgärder"],
  },
  {
    name: "individ-redigera",
    role: "owner",
    path: "/stamboken/individ/G1274-2117",
    actions: ["click:Redigera"],
  },
  {
    name: "rapportera-dod",
    role: "owner",
    path: "/stamboken/individ/G1274-2117",
    actions: ["click:Fler åtgärder", "menuitem:Rapportera död"],
  },
  {
    name: "salj-individ",
    role: "owner",
    path: "/stamboken/individ/G1274-2117",
    actions: ["click:Fler åtgärder", "menuitem:Sälj individ"],
  },
  {
    name: "alla-kaniner",
    role: "owner",
    path: "/stamboken/alla-kaniner",
    actions: ["wait:4000"],
  },
  {
    name: "provparning",
    role: "owner",
    path: "/stamboken/provparning?genebank=1&hona=G1274-2117&hane=G1274-2116",
    actions: ["wait:4000"],
    fullPage: true,
  },
  { name: "profil", role: "owner", path: "/stamboken/profil" },
  {
    name: "genetik-oversikt",
    role: "manager",
    path: "/stamboken/genetik?genebank=1",
    actions: ["wait:8000"],
    fullPage: true,
  },
  {
    name: "genetik-prioriteringar",
    role: "manager",
    path: "/stamboken/genetik?genebank=1&tab=prioriteringar",
    actions: ["wait:8000"],
  },
  {
    name: "genetik-parningsforslag",
    role: "manager",
    path: "/stamboken/genetik?genebank=1&tab=parningsforslag",
    actions: ["wait:3000", "click:Beräkna", "wait:8000"],
  },
  {
    name: "individ-andringshistorik",
    role: "manager",
    path: "/stamboken/individ/G1274-2117",
    actions: ["scroll:Ändringshistorik"],
  },
  { name: "admin", role: "admin", path: "/stamboken/admin" },
  {
    name: "admin-anvandare",
    role: "admin",
    path: "/stamboken/admin/anvandare",
  },
  {
    name: "admin-anvandare-detalj",
    role: "admin",
    path: "/stamboken/admin/anvandare/9",
    fullPage: true,
  },
  {
    name: "admin-besattningar",
    role: "admin",
    path: "/stamboken/admin/besattningar",
  },
  {
    name: "admin-besattning-detalj",
    role: "admin",
    path: "/stamboken/admin/besattningar/G1274",
    fullPage: true,
  },
  {
    name: "admin-ny-besattning",
    role: "admin",
    path: "/stamboken/admin/besattningar/ny",
    fullPage: true,
  },
  {
    name: "admin-genbanker",
    role: "admin",
    path: "/stamboken/admin/genbanker",
  },
  {
    name: "admin-genbank-detalj",
    role: "admin",
    path: "/stamboken/admin/genbanker/1",
  },
  { name: "admin-system", role: "admin", path: "/stamboken/admin/system" },
  {
    name: "admin-aktiva-anvandare",
    role: "admin",
    path: "/stamboken/admin/system/online",
  },
  {
    name: "admin-aktivitetslogg",
    role: "admin",
    path: "/stamboken/admin/system/audit",
  },
  {
    name: "admin-demosynk",
    role: "admin",
    path: "/stamboken/admin/system/synk",
  },
  {
    name: "admin-anropsgranser",
    role: "admin",
    path: "/stamboken/admin/system/ratelimit",
  },
  { name: "manager-admin", role: "manager", path: "/stamboken/admin" },
  {
    name: "manager-besattningar",
    role: "manager",
    path: "/stamboken/admin/besattningar",
  },
];
if (process.env.MANUAL_CERT_UUID) {
  SHOTS.push({
    name: "verifiera-intyg",
    role: "anonymous",
    path: `/stamboken/verifiera/${process.env.MANUAL_CERT_UUID}`,
  });
}

async function login(page: Page, context: BrowserContext, role: Role) {
  await context.clearCookies();
  if (role === "anonymous") return;
  const { username, password } = USERS[role];
  const res = await page.request.post("/api/login", {
    data: { username, password },
  });
  expect(res.ok(), `login ${username}: ${res.status()}`).toBeTruthy();
  // sb_mode=prod: adminpanelen och "riktiga stamboken"-vyn utan testmiljö-banner.
  await context.addCookies([
    {
      name: "sb_mode",
      value: "prod",
      domain: "localhost",
      path: "/",
      sameSite: "Lax",
    },
  ]);
}

async function act(page: Page, action: string) {
  const i = action.indexOf(":");
  const kind = action.slice(0, i);
  const arg = action.slice(i + 1);
  switch (kind) {
    case "wait":
      await page.waitForTimeout(Number(arg));
      return;
    case "click":
      await page
        .getByRole("button", { name: arg, exact: true })
        .first()
        .click();
      break;
    case "button":
      await page
        .getByRole("button", { name: arg, exact: true })
        .first()
        .click();
      break;
    case "menuitem":
      await page.getByRole("menuitem", { name: arg }).click();
      break;
    case "card":
      // Första kullen med texten (nyaste först): testkullen från mutation-manual-flows.
      await page
        .locator('[data-testid="breeding-card"]')
        .filter({ hasText: arg })
        .first()
        .getByRole("button", { name: "Detaljer" })
        .click();
      break;
    case "scroll":
      await page
        .getByRole("heading", { name: arg })
        .first()
        .scrollIntoViewIfNeeded();
      break;
  }
  await page.waitForTimeout(800);
}

for (const shot of SHOTS) {
  for (const [suffix, viewport] of [
    ["mobil", { width: 375, height: 812 }],
    ["desktop", { width: 1280, height: 800 }],
  ] as const) {
    test(`${shot.name} (${suffix})`, async ({ page, context }) => {
      await page.setViewportSize(viewport);
      await login(page, context, shot.role);
      await page.goto(shot.path, { waitUntil: "networkidle" });
      await page
        .getByText("Laddar")
        .first()
        .waitFor({ state: "hidden", timeout: 20000 })
        .catch(() => {});
      // Next.js dev-verktygens knapp ska inte med på bilderna.
      await page.addStyleTag({
        content: "nextjs-portal { display: none !important; }",
      });
      // Beta-bannern tar plats på varje bild; stäng den (valet sparas i webbläsaren).
      const beta = page
        .getByRole("alert")
        .filter({ hasText: "nya Stamboken" })
        .getByRole("button", { name: "Stäng" });
      if (await beta.isVisible().catch(() => false)) await beta.click();
      for (const a of shot.actions ?? []) await act(page, a);
      await page.waitForTimeout(500);
      await page.screenshot({
        path: path.join(OUT, `${shot.name}-${suffix}.png`),
        fullPage: shot.fullPage ?? false,
      });
    });
  }
}
