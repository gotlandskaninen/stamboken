"use client";

// Klientkomponent enbart för usePathname (aktiv flik + aria-current) — det
// den gamla sidomenyn aldrig hade. Länkarna är <Link>-element, inte component={Link},
// så inget funktionsprop passerar RSC-gränsen (se AdminLink.tsx:3-7).
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SbIcon, type SbIconName } from "@/components/shell/SbIcon";
import type { UserContext } from "@/lib/user-context";
import { NAV_CONFIG } from "./navConfig";
import styles from "../admin.module.css";

const ADMIN_ROOT = "/stamboken/admin";

/**
 * Gruppetikett → flikchrome. navConfig.ts lämnas orörd (dess enhetstest
 * låser versala gruppetiketter och href-ordningen), så mening-versal
 * fliketikett och ikon bor här. scoped: true = använd postens label(ctx)
 * för icke-admin, vilket är det som renderar "Besättningar i <genbank>"
 * (e2e/admin/03-manager-scoped-view.spec.ts:29).
 */
const TAB_META: Record<
  string,
  { label: string; icon: SbIconName; scoped?: boolean }
> = {
  ANVÄNDARE: { label: "Användare", icon: "user" },
  BESÄTTNINGAR: { label: "Besättningar", icon: "home", scoped: true },
  GENBANKER: { label: "Genbanker", icon: "rabbit" },
  SYSTEM: { label: "System", icon: "cog" },
};

/** /stamboken/admin/system/online → /stamboken/admin/system */
const sectionKey = (href: string) => href.split("/").slice(0, 4).join("/");

export function AdminTabs({
  user,
  gbNames,
}: {
  user: UserContext;
  gbNames?: string[];
}) {
  const pathname = usePathname();
  const ctx = { user, gbNames };

  const tabs = [
    {
      key: ADMIN_ROOT,
      href: ADMIN_ROOT,
      label: "Översikt",
      icon: "grid" as SbIconName,
    },
    ...NAV_CONFIG.flatMap((group) => {
      const visible = group.items.filter((i) => i.show(ctx));
      const meta = TAB_META[group.label];
      // Ny grupp i navConfig utan TAB_META → ingen flik (hellre tyst än trasig).
      if (visible.length === 0 || !meta) return [];
      const href = visible[0].href; // SYSTEM: första synliga undersidan
      return [
        {
          key: sectionKey(href),
          href,
          label:
            meta.scoped && !user.is_admin ? visible[0].label(ctx) : meta.label,
          icon: meta.icon,
        },
      ];
    }),
  ];

  // Längsta matchande sektionsprefix vinner, så /system/audit aktiverar
  // System och bara /stamboken/admin aktiverar Översikt.
  const activeKey = tabs
    .map((t) => t.key)
    .filter((k) => pathname === k || pathname.startsWith(`${k}/`))
    .sort((a, b) => b.length - a.length)[0];

  return (
    <nav className={styles["ad-tabs-wrap"]} aria-label="Adminpanelens avsnitt">
      <div className={styles["ad-container"]}>
        <div className={styles["ad-tabs"]} role="tablist">
          {tabs.map((tab) => {
            const active = tab.key === activeKey;
            return (
              <Link
                key={tab.key}
                href={tab.href}
                role="tab"
                aria-selected={active}
                aria-current={active ? "page" : undefined}
                className={`${styles["ad-tab"]} ${active ? styles["is-active"] : ""}`}
              >
                <SbIcon name={tab.icon} size={16} />
                {tab.label}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
