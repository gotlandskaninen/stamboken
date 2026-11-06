import Link from "next/link";
import styles from "../admin.module.css";

// Hrefs + labels mirror navConfig.ts:69-88 (SYSTEM group). navConfig.ts is
// pinned exactly by navConfig.test.ts, so the pill nav keeps its own copy
// rather than reaching into NAV_CONFIG's group/predicate structure. All four
// pages are admin-only, so there is no role gating here — requireAdmin() on
// each page is the gate.
const SYSTEM_PAGES = [
  {
    id: "online",
    href: "/stamboken/admin/system/online",
    label: "Aktiva användare",
  },
  {
    id: "audit",
    href: "/stamboken/admin/system/audit",
    label: "Aktivitetslogg",
  },
  {
    id: "synk",
    href: "/stamboken/admin/system/synk",
    label: "Demosynkronisering",
  },
  {
    id: "ratelimit",
    href: "/stamboken/admin/system/ratelimit",
    label: "Anropsgränser",
  },
] as const;

export type SystemPageId = (typeof SYSTEM_PAGES)[number]["id"];

/**
 * Undernav för System (handoff README rad 27). Pillren är riktiga länkar
 * till egna sidor — därför <nav> + aria-current="page", INTE role="tablist"
 * (tablist kräver att panelerna byts i samma dokument).
 */
export function SystemPillNav({ current }: { current: SystemPageId }) {
  return (
    <nav aria-label="Systemsidor" className={styles["ad-pill-row"]}>
      {SYSTEM_PAGES.map((p) => (
        <Link
          key={p.id}
          href={p.href}
          aria-current={p.id === current ? "page" : undefined}
          className={
            p.id === current
              ? `${styles["ad-pill"]} ${styles["is-active"]}`
              : styles["ad-pill"]
          }
        >
          {p.label}
        </Link>
      ))}
    </nav>
  );
}
