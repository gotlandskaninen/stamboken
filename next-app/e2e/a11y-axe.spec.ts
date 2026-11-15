import { test } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { appendFileSync, readdirSync } from "node:fs";
import type { Page } from "@playwright/test";
import { loginInline, TEST_USERS } from "../e2e-shared/auth";

// Rådgivande: en överträdelse fäller aldrig testet. Resultatet visas i
// konsolen, som bilaga och (i CI) på Actions-körningens sammanfattning.
test.use({
  viewport: { width: 375, height: 812 },
  hasTouch: true,
  isMobile: true,
});

type Role = "anon" | keyof typeof TEST_USERS;
type Ids = Record<"user" | "herd" | "gb" | "membership", string | undefined>;
// Sträng = url; funktion = url ur seed-id (undefined = saknar testdata);
// [null, skäl] = kan inte kontrolleras med seed-datat.
type Target = string | ((ids: Ids) => string | undefined) | [null, string];

// route (page.tsx-sökvägen utan route-grupper) -> roll och konkret url.
// Id:n slås upp ur seed-datat via admin-API:t; CMS-sidor och ansökningar finns inte där.
const PAGES: Record<string, [Role, Target]> = {
  "/": ["anon", "/"],
  "/[slug]": ["anon", [null, "saknar testdata"]],
  "/preview/[slug]": ["admin", [null, "saknar testdata"]],
  "/ansok": ["anon", "/ansok"],
  "/bli-genbank": ["anon", "/bli-genbank"],
  "/bli-genbanksbesattning": ["anon", "/bli-genbanksbesattning"],
  "/medlemsforum": ["anon", "/medlemsforum"],
  "/stamboken-online": ["anon", "/stamboken-online"],
  "/stamboken-online/kom-igang": ["anon", "/stamboken-online/kom-igang"],
  "/stamboken-online/manual": ["anon", "/stamboken-online/manual"],
  "/auth/sign-in": ["anon", "/auth/sign-in"],
  "/error/404": ["anon", "/error/404"],
  "/error/500": ["anon", "/error/500"],
  // Påhittat uuid: sidan visar "ogiltigt intyg", och det är den som granskas.
  "/stamboken/verifiera/[uuid]": [
    "anon",
    "/stamboken/verifiera/00000000-0000-0000-0000-000000000000",
  ],
  "/stamboken/min-besattning": ["owner", "/stamboken/min-besattning"],
  "/stamboken/profil": ["owner", "/stamboken/profil"],
  "/stamboken/provparning": ["owner", "/stamboken/provparning"],
  "/stamboken/alla-kaniner": ["owner", "/stamboken/alla-kaniner"],
  "/stamboken/genetik": ["owner", "/stamboken/genetik"],
  "/stamboken/individ/[number]": ["owner", "/stamboken/individ/G1274-2112"],
  "/stamboken/admin": ["admin", "/stamboken/admin"],
  "/stamboken/admin/anvandare": ["admin", "/stamboken/admin/anvandare"],
  "/stamboken/admin/anvandare/[userId]": [
    "admin",
    (i) => i.user && `/stamboken/admin/anvandare/${i.user}`,
  ],
  "/stamboken/admin/besattningar": ["admin", "/stamboken/admin/besattningar"],
  "/stamboken/admin/besattningar/ny": [
    "admin",
    "/stamboken/admin/besattningar/ny",
  ],
  "/stamboken/admin/besattningar/[herdId]": [
    "admin",
    (i) => i.herd && `/stamboken/admin/besattningar/${i.herd}`,
  ],
  "/stamboken/admin/genbanker": ["admin", "/stamboken/admin/genbanker"],
  "/stamboken/admin/genbanker/[gbId]": [
    "admin",
    (i) => i.gb && `/stamboken/admin/genbanker/${i.gb}`,
  ],
  "/stamboken/admin/system": ["admin", "/stamboken/admin/system"],
  "/stamboken/admin/system/audit": ["admin", "/stamboken/admin/system/audit"],
  "/stamboken/admin/system/online": ["admin", "/stamboken/admin/system/online"],
  "/stamboken/admin/system/ratelimit": [
    "admin",
    "/stamboken/admin/system/ratelimit",
  ],
  "/stamboken/admin/system/synk": ["admin", "/stamboken/admin/system/synk"],
  "/medlem/ansokningar": ["admin", "/medlem/ansokningar"],
  "/medlem/ansokningar/[id]": ["admin", [null, "saknar testdata"]],
  "/medlem/matrikel": ["admin", "/medlem/matrikel"],
  "/medlem/matrikel/[id]": [
    "admin",
    (i) => i.membership && `/medlem/matrikel/${i.membership}`,
  ],
  "/medlem/statistik": ["admin", "/medlem/statistik"],
  "/admin/[[...segments]]": ["admin", "/admin"],
};

const API = process.env.E2E_API_URL ?? "http://localhost:9090";
const BUDGET_MS = 8 * 60_000;
const LEVELS = ["critical", "serious", "moderate", "minor"] as const;
const ADMIN_PROMPT = "Adminpanelen finns i den riktiga stamboken";

// Rådgivande ska aldrig fälla CI: allt som kan kasta går genom safe().
function safe<T>(f: () => T, fallback: T): T {
  try {
    return f();
  } catch {
    return fallback;
  }
}

// Samma regel som scripts/check-manual-coverage.sh: route-grupper "(…)" bort.
const onDisk = safe(
  () =>
    readdirSync("src/app", { recursive: true })
      .map(String)
      .filter((f) => f.endsWith("page.tsx"))
      .map(
        (f) => "/" + f.replace(/\([^/]*\)\//g, "").replace(/\/?page\.tsx$/, ""),
      ),
  [] as string[],
);

const within = <T>(p: Promise<T>, ms: number) =>
  Promise.race([
    p,
    new Promise<never>((_, rej) =>
      setTimeout(() => rej(new Error(`tidsgräns ${ms / 1000} s`)), ms),
    ),
  ]);

// Första id:t i första listan i svaret, t.ex. {herds: [{id: 3}, …]}.
async function firstId(page: Page, path: string) {
  try {
    const body = await (await page.request.get(`${API}/api${path}`)).json();
    const list = Object.values(body).find(Array.isArray) as
      | { id?: unknown }[]
      | undefined;
    return list?.[0]?.id === undefined ? undefined : String(list[0].id);
  } catch {
    return undefined;
  }
}

type Row = { route: string; role: Role; text: string };

test("axe över alla sidor (rådgivande)", async ({ page, context }) => {
  test.setTimeout(15 * 60_000);
  const started = Date.now();
  const rows: Row[] = [];
  const todo = Object.entries(PAGES).sort((a, b) =>
    a[1][0].localeCompare(b[1][0]),
  ); // admin först: id:na ur seed-datat hämtas med admins session
  let ids: Ids = {
    user: undefined,
    herd: undefined,
    gb: undefined,
    membership: undefined,
  };
  let current: Role | undefined;

  try {
    for (const [route, [role, target]] of todo) {
      const row = (text: string) => {
        rows.push({ route, role, text });
        console.log(`axe ${route} [${role}]: ${text}`);
      };
      if (Date.now() - started > BUDGET_MS) {
        row("hann inte");
        continue;
      }
      if (Array.isArray(target)) {
        row(`inte kontrollerad (${target[1]})`);
        continue;
      }
      const counts = Object.fromEntries(LEVELS.map((l) => [l, 0]));
      const rules: Record<string, { impact: string; nodes: number }> = {};
      let verdict = "";
      let url = typeof target === "string" ? target : "";
      try {
        if (role !== current) {
          if (role === "anon") await context.clearCookies();
          else {
            await loginInline(page, context, TEST_USERS[role]);
            // Adminlayouten visar annars bara "byt till riktiga stamboken".
            await context.addCookies([
              {
                name: "sb_mode",
                value: "prod",
                domain: "localhost",
                path: "/",
              },
            ]);
          }
          current = role;
          if (role === "admin")
            ids = {
              user: await firstId(page, "/v2/admin/users?per_page=1"),
              herd: await firstId(page, "/manage/herd?per_page=1"),
              gb: await firstId(page, "/genebanks"),
              membership: await firstId(page, "/v2/memberships?per_page=1"),
            };
        }
        if (typeof target === "function") {
          const u = target(ids);
          if (!u) {
            row("inte kontrollerad (saknar testdata)");
            continue;
          }
          url = u;
        }
        const res = await page.goto(url, {
          waitUntil: "networkidle",
          timeout: 20_000,
        });
        await page
          .locator("main:visible, form:visible, h1:visible, a:visible")
          .first()
          .waitFor({ timeout: 10_000 });
        const path = new URL(page.url()).pathname;
        if (path !== url.split("?")[0]) verdict = `omdirigerad till ${path}`;
        else if (res && res.status() >= 400) verdict = `HTTP ${res.status()}`;
        else if (await page.getByText(ADMIN_PROMPT).isVisible())
          verdict = "adminpanelens lägesfråga visas";
        if (verdict) {
          row(`inte kontrollerad (${verdict})`);
          continue;
        }
        const { violations } = await within(
          new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
            .analyze(),
          30_000,
        );
        for (const v of violations) {
          counts[v.impact ?? "minor"]++;
          rules[v.id] = { impact: v.impact ?? "minor", nodes: v.nodes.length };
        }
      } catch (e) {
        row(
          `kunde inte kontrolleras (${String(e).split("\n")[0].slice(0, 80)})`,
        );
        continue;
      }
      const top = Object.entries(rules)
        .sort((a, b) => b[1].nodes - a[1].nodes)
        .slice(0, 3)
        .map(([id, r]) => `${id} (${r.nodes})`)
        .join(", ");
      const h1 = await page
        .locator("h1:visible")
        .first()
        .innerText({ timeout: 1000 })
        .catch(() => "");
      await test
        .info()
        .attach(`axe-${route}`, {
          body: JSON.stringify({ route, role, url, counts, rules }, null, 2),
          contentType: "application/json",
        })
        .catch(() => {});
      row(
        `${LEVELS.map((l) => counts[l]).join("/")} krit/allv/måttl/lätt ${top} | h1: ${h1.slice(0, 40)}`,
      );
    }
  } finally {
    const done = new Set(rows.map((r) => r.route));
    const missed = onDisk.filter((r) => !(r in PAGES));
    const unreached = Object.keys(PAGES).filter((r) => !done.has(r));
    const table = rows
      .map((r) => {
        const m = r.text.match(
          /^(\d+)\/(\d+)\/(\d+)\/(\d+) krit\/allv\/måttl\/lätt (.*?) \|/,
        );
        return m
          ? `| ${r.route} | ${r.role} | ${m[1]} | ${m[2]} | ${m[3]} | ${m[4]} | ${m[5]} |`
          : `| ${r.route} | ${r.role} | – | – | – | – | ${r.text} |`;
      })
      .join("\n");
    const extra = [
      missed.length && `Sidor som specen inte besöker: ${missed.join(", ")}`,
      unreached.length && `Hann inte: ${unreached.join(", ")}`,
    ].filter(Boolean);
    extra.forEach((x) => console.log(`axe: ${x}`));
    const summary = process.env.GITHUB_STEP_SUMMARY;
    if (summary)
      safe(
        () =>
          appendFileSync(
            summary,
            `\n## Tillgänglighet (axe, rådgivande)\n\n| Route | Roll | Kritiska | Allvarliga | Måttliga | Lätta | Vanligaste regler / status |\n|---|---|---|---|---|---|---|\n${table}\n${extra.map((x) => `\n${x}\n`).join("")}`,
          ),
        undefined,
      );
  }
});
