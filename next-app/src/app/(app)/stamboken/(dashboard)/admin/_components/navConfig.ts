import type { UserContext } from "@/lib/user-context";

/**
 * Groups/items for the admin sidebar. The same show() predicates drive
 * sidebar visibility, the landing card grid and the layout-level
 * 404 (hasAnyVisible). Adding a new admin page = one entry here.
 *
 * gbNames: resolved genebank names for the caller's is_manager ids — only
 * needed for the manager label variants ("Besättningar i <gb-name>").
 */
export type NavCtx = { user: UserContext; gbNames?: string[] };

export type AdminNavItem = {
  href: string;
  label: (ctx: NavCtx) => string;
  show: (ctx: NavCtx) => boolean;
};

export type AdminNavGroup = {
  label: string;
  items: AdminNavItem[];
};

const isAdmin = ({ user }: NavCtx) => user.is_admin;
const isManager = ({ user }: NavCtx) =>
  Array.isArray(user.is_manager) && user.is_manager.length > 0;
const isAdminOrManager = (ctx: NavCtx) => isAdmin(ctx) || isManager(ctx);

/**
 * Medlemsregistret (/medlem/matrikel, /medlem/ansokningar,
 * /medlem/statistik) ligger utanför adminpanelens layout och får därför
 * ingen flik i NAV_CONFIG — men landningskortet, avatar-menyn och
 * layout-gaten delar detta predikat (samma trio som API:ets
 * check_matrikel_access: admin, genbanksansvarig eller matrikeladmin).
 */
export const isMemberAdmin = (user: UserContext): boolean =>
  isAdminOrManager({ user }) || Boolean(user.is_matrikel_admin);

/** Besättningar/Genbanker-korten: admin eller genbanksansvarig. */
export const isHerdAdmin = (user: UserContext): boolean =>
  isAdminOrManager({ user });

/** Mastheadens roll-rad. `hasAnyVisible` släpper även in matrikeladmins
 *  (utan genbank) — de ska inte presenteras som genbanksansvariga. */
export function adminRoleLine(user: UserContext, gbNames?: string[]): string {
  if (user.is_admin) return "Inloggad som administratör";
  if (isHerdAdmin(user)) {
    return gbNames?.length
      ? `Inloggad som genbanksansvarig · ${gbNames.join(", ")}`
      : "Inloggad som genbanksansvarig";
  }
  return "Inloggad som matrikeladministratör";
}

export const NAV_CONFIG: AdminNavGroup[] = [
  {
    label: "ANVÄNDARE",
    items: [
      {
        href: "/stamboken/admin/anvandare",
        label: () => "Alla användare",
        show: isAdmin,
      },
    ],
  },
  {
    label: "BESÄTTNINGAR",
    items: [
      {
        href: "/stamboken/admin/besattningar",
        label: (ctx) =>
          isAdmin(ctx)
            ? "Alla besättningar"
            : (ctx.gbNames ?? []).length > 0
              ? `Besättningar i ${(ctx.gbNames ?? []).join(", ")}`
              : "Besättningar du ansvarar för",
        show: isAdminOrManager,
      },
    ],
  },
  {
    label: "GENBANKER",
    items: [
      {
        href: "/stamboken/admin/genbanker",
        label: (ctx) =>
          isAdmin(ctx) ? "Alla genbanker" : "Genbanker du ansvarar för",
        show: isAdminOrManager,
      },
    ],
  },
  {
    label: "SYSTEM",
    items: [
      {
        href: "/stamboken/admin/system/online",
        label: () => "Aktiva användare",
        show: isAdmin,
      },
      {
        href: "/stamboken/admin/system/audit",
        label: () => "Aktivitetslogg",
        show: isAdmin,
      },
      {
        href: "/stamboken/admin/system/synk",
        label: () => "Demosynkronisering",
        show: isAdmin,
      },
      {
        href: "/stamboken/admin/system/ratelimit",
        label: () => "Anropsgränser",
        show: isAdmin,
      },
    ],
  },
];

/** Layout-level 404 + user-menu predicate. */
export function hasAnyVisible(user: UserContext): boolean {
  return (
    NAV_CONFIG.some((g) => g.items.some((i) => i.show({ user }))) ||
    isMemberAdmin(user)
  );
}
