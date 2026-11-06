// Samma landningskort som adminpanelens översikt — AdminLandingCard är
// den delade komponenten.
import { requireAdmin } from "../_lib/requireAdmin";
import { AdminLandingCard } from "../_components/AdminLandingCard";
import type { SbIconName } from "@/components/shell/SbIcon";
import ds from "@/styles/ds-admin.module.css";
import styles from "../admin.module.css";

const CARDS: {
  href: string;
  title: string;
  description: string;
  icon: SbIconName;
}[] = [
  {
    href: "/stamboken/admin/system/online",
    title: "Aktiva användare",
    description:
      "Se vilka som nyligen varit aktiva och logga vid behov ut alla användare.",
    icon: "users",
  },
  {
    href: "/stamboken/admin/system/audit",
    title: "Aktivitetslogg",
    description: "Sök bland ändringar i stamboken.",
    icon: "book",
  },
  {
    href: "/stamboken/admin/system/synk",
    title: "Demosynkronisering",
    description:
      "Se när demoversionen senast uppdaterades och om uppdateringen lyckades.",
    icon: "download",
  },
  {
    href: "/stamboken/admin/system/ratelimit",
    title: "Anropsgränser",
    description:
      "Kontrollera att skyddet mot för många anrop är aktiverat och fungerar.",
    icon: "shield",
  },
];

export default async function SystemLandingPage() {
  await requireAdmin(); // Page-level gate, layout renders concurrently
  return (
    <>
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>System</h2>
      </div>
      <div className={styles["ad-landing-grid"]}>
        {CARDS.map((c) => (
          <AdminLandingCard key={c.href} {...c} />
        ))}
      </div>
    </>
  );
}
