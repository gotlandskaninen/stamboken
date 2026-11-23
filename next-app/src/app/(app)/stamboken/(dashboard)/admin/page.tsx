import { getUser } from "@/lib/auth";
import { fetchApi } from "@/lib/api";
import {
  hasAnyVisible,
  isHerdAdmin,
  isMemberAdmin,
} from "./_components/navConfig";
import { AdminLandingCard } from "./_components/AdminLandingCard";
import type { SbIconName } from "@/components/shell/SbIcon";
import ds from "@/styles/ds-admin.module.css";
import styles from "./admin.module.css";

export const dynamic = "force-dynamic";

type GenebankShort = {
  id: number;
  name: string;
  herds: { is_active: boolean }[];
};

type AdminCard = {
  href: string;
  title: string;
  description: string;
  countLabel: string | null;
  icon: SbIconName;
};

/**
 * Card counts are cheap RSC fetches — `total` from the paginated
 * endpoints without pulling rows. Count failures degrade to a count-less
 * card, never an error page. Envelope: { total } per Tasks 14/17 —
 * verify field name against the backend implementation.
 */
async function safeCount(path: string): Promise<number | null> {
  try {
    const body = await fetchApi<{ total?: number }>(path, { forceProd: true });
    return typeof body.total === "number" ? body.total : null;
  } catch {
    return null;
  }
}

export default async function AdminLandingPage() {
  const user = await getUser();
  if (!user) return null; // layout already gated — belt only
  if (!hasAnyVisible(user)) {
    // Empty-state safety net behind the layout gate.
    return (
      <p className={ds["ad-hint"]}>
        Du har ingen behörighet till adminpanelen. Kontakta styrelsen.
      </p>
    );
  }

  const isAdmin = user.is_admin;
  const memberAdmin = isMemberAdmin(user);
  // En ren matrikeladmin passerar layout-gaten via isMemberAdmin men har
  // inga besättnings-/genbankssidor — de korten kräver admin/ansvarig.
  const herdAdmin = isHerdAdmin(user);
  const [usersCount, adminHerdsCount, genebanks, membershipsCount] =
    await Promise.all([
      isAdmin ? safeCount("/v2/admin/users?per_page=1") : Promise.resolve(null),
      // GET /api/manage/herd is admin-only in Phase 17.
      isAdmin ? safeCount("/manage/herd?per_page=1") : Promise.resolve(null),
      // Envelope: { genebanks: [...] }, same as admin/layout.tsx.
      fetchApi<{ genebanks: GenebankShort[] }>("/genebanks", {
        forceProd: true,
      })
        .then((b) => b.genebanks)
        .catch(() => null),
      // Matrikellistans envelope: { items, total, page, per_page }.
      memberAdmin ? safeCount("/v2/members?per_page=1") : Promise.resolve(null),
    ]);

  // Manager herd count comes from the already-accessible /genebanks payload.
  const managerGbs = isAdmin
    ? []
    : (genebanks ?? []).filter((g) => user.is_manager?.includes(g.id));
  const herdsCount = isAdmin
    ? adminHerdsCount
    : managerGbs.reduce(
        (n, g) => n + g.herds.filter((h) => h.is_active).length,
        0,
      );
  const herdsWord = herdsCount === 1 ? "besättning" : "besättningar";
  const herdsCountLabel =
    herdsCount === null
      ? null
      : !isAdmin && managerGbs.length === 1
        ? `${herdsCount} ${herdsWord} i ${managerGbs[0].name}`
        : `${herdsCount} ${herdsWord}`;
  const gbCount = isAdmin ? (genebanks?.length ?? null) : managerGbs.length;

  const cards: AdminCard[] = [
    ...(isAdmin
      ? ([
          {
            href: "/stamboken/admin/anvandare",
            title: "Användare",
            description: "Sök, granska och redigera användarkonton.",
            countLabel: usersCount === null ? null : `${usersCount} användare`,
            icon: "users",
          },
        ] satisfies AdminCard[])
      : []),
    ...(herdAdmin
      ? ([
          {
            href: "/stamboken/admin/besattningar",
            title: "Besättningar",
            description:
              "Redigera uppgifter, skapa nya besättningar och byt ägare.",
            countLabel: herdsCountLabel,
            icon: "home",
          },
          {
            href: "/stamboken/admin/genbanker",
            title: "Genbanker",
            description: "Redigera uppgifter om genbanker.",
            countLabel:
              gbCount === null
                ? null
                : `${gbCount} ${gbCount === 1 ? "genbank" : "genbanker"}`,
            icon: "rabbit",
          },
          {
            href: "/stamboken/admin/utskick",
            title: "Utskick",
            description: "Status för utgående e-post, med omförsök och stopp.",
            countLabel: null,
            icon: "mail",
          },
        ] satisfies AdminCard[])
      : []),
    // Utlänk: /medlem har egen layout utan adminflikar (navConfig.isMemberAdmin).
    ...(memberAdmin
      ? ([
          {
            href: "/medlem/matrikel",
            title: "Medlemsregister",
            description: "Matrikel, medlemsansökningar och statistik.",
            countLabel:
              membershipsCount === null
                ? null
                : `${membershipsCount} medlemskap`,
            icon: "book",
          },
        ] satisfies AdminCard[])
      : []),
    ...(isAdmin
      ? ([
          {
            href: "/stamboken/admin/system",
            title: "System",
            description:
              "Aktiva användare, aktivitetslogg, demosynkronisering och anropsgränser.",
            countLabel: null,
            icon: "cog",
          },
        ] satisfies AdminCard[])
      : []),
  ];

  // Rubriken "Adminpanel" bor i layoutens masthead — sidan får inte
  // rendera en andra (e2e/admin/04-admin-mode-gate.spec.ts:28,:39 gör
  // getByRole("heading", { name: "Adminpanel" }) och blir strict-mode-
  // tvetydig om båda finns).
  return (
    <div className={styles["ad-landing-grid"]}>
      {cards.map((c) => (
        <AdminLandingCard key={c.href} {...c} />
      ))}
    </div>
  );
}
