import { test, expect } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { appendFileSync, readdirSync } from "node:fs";
import { loginInline, TEST_USERS } from "../e2e-shared/auth";

// Rådgivande: en överträdelse fäller aldrig testet. Resultatet visas i
// konsolen, som bilaga och (i CI) på Actions-körningens sammanfattning.
test.use({
  viewport: { width: 375, height: 812 },
  hasTouch: true,
  isMobile: true,
});

type Role = "anon" | keyof typeof TEST_USERS;

// route (page.tsx-sökvägen utan route-grupper) -> roll och konkret url.
// Numeriska id:n finns inte i seed-datat; sidan visar då sin 404, som också granskas.
const PAGES: Record<string, [Role, string]> = {
  "/": ["anon", "/"],
  "/[slug]": ["anon", "/bli-medlem"],
  "/preview/[slug]": ["admin", "/preview/bli-medlem"],
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
    "/stamboken/admin/anvandare/1",
  ],
  "/stamboken/admin/besattningar": ["admin", "/stamboken/admin/besattningar"],
  "/stamboken/admin/besattningar/ny": [
    "admin",
    "/stamboken/admin/besattningar/ny",
  ],
  "/stamboken/admin/besattningar/[herdId]": [
    "admin",
    "/stamboken/admin/besattningar/1",
  ],
  "/stamboken/admin/genbanker": ["admin", "/stamboken/admin/genbanker"],
  "/stamboken/admin/genbanker/[gbId]": [
    "admin",
    "/stamboken/admin/genbanker/1",
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
  "/medlem/ansokningar/[id]": ["admin", "/medlem/ansokningar/1"],
  "/medlem/matrikel": ["admin", "/medlem/matrikel"],
  "/medlem/matrikel/[id]": ["admin", "/medlem/matrikel/1"],
  "/medlem/statistik": ["admin", "/medlem/statistik"],
  "/admin/[[...segments]]": ["admin", "/admin"],
};

// Samma regel som scripts/check-manual-coverage.sh: route-grupper "(…)" bort.
const onDisk = readdirSync("src/app", { recursive: true })
  .map(String)
  .filter((f) => f.endsWith("page.tsx"))
  .map((f) => "/" + f.replace(/\([^/]*\)\//g, "").replace(/\/?page\.tsx$/, ""));

const LEVELS = ["critical", "serious", "moderate", "minor"] as const;

test("axe över alla sidor (rådgivande)", async ({ page, context }) => {
  test.setTimeout(15 * 60_000);
  const missed = onDisk.filter((r) => !(r in PAGES));
  const rows: string[] = [];

  // Sorterat på roll: inloggningen är hastighetsbegränsad (429), så en per roll.
  let current: Role | undefined;
  const byRole = Object.entries(PAGES).sort((a, b) =>
    a[1][0].localeCompare(b[1][0]),
  );
  for (const [route, [role, url]] of byRole) {
    const counts = Object.fromEntries(LEVELS.map((l) => [l, 0]));
    const rules: Record<string, { impact: string; nodes: number }> = {};
    let note = "";
    try {
      if (role !== current) {
        if (role === "anon") await context.clearCookies();
        else await loginInline(page, context, TEST_USERS[role]);
        current = role;
      }
      const res = await page.goto(url, { waitUntil: "networkidle" });
      await expect(
        page
          .locator("main:visible, form:visible, h1:visible, a:visible")
          .first(),
      ).toBeVisible();
      if (res && res.status() >= 400) note = ` (HTTP ${res.status()})`;
      const { violations } = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();
      for (const v of violations) {
        counts[v.impact ?? "minor"]++;
        rules[v.id] = { impact: v.impact ?? "minor", nodes: v.nodes.length };
      }
    } catch (e) {
      note = "kunde inte kontrolleras";
      console.log(`axe ${route}: ${String(e).split("\n")[0]}`);
    }
    await test.info().attach(`axe-${route}`, {
      body: JSON.stringify({ route, role, url, counts, rules, note }, null, 2),
      contentType: "application/json",
    });
    const top = Object.entries(rules)
      .sort((a, b) => b[1].nodes - a[1].nodes)
      .slice(0, 3)
      .map(([id, r]) => `${id} (${r.nodes})`)
      .join(", ");
    console.log(
      `axe ${route} [${role}]: ${LEVELS.map((l) => counts[l]).join("/")} krit/allv/måttl/lätt ${top}${note}`,
    );
    rows.push(
      note === "kunde inte kontrolleras"
        ? `| ${route} | ${role} | – | – | – | – | kunde inte kontrolleras |`
        : `| ${route} | ${role} | ${LEVELS.map((l) => counts[l]).join(" | ")} | ${top}${note} |`,
    );
  }

  if (missed.length)
    console.log(`axe: sidor som specen inte besöker: ${missed.join(", ")}`);
  const summary = process.env.GITHUB_STEP_SUMMARY;
  if (summary) {
    appendFileSync(
      summary,
      `\n## Tillgänglighet (axe, rådgivande)\n\n| Route | Roll | Kritiska | Allvarliga | Måttliga | Lätta | Vanligaste regler |\n|---|---|---|---|---|---|---|\n${rows.join("\n")}\n` +
        (missed.length
          ? `\nSidor som specen inte besöker: ${missed.map((r) => `\`${r}\``).join(", ")}\n`
          : ""),
    );
  }
});
