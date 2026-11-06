import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, fetchApi } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { Masthead } from "@/components/shell/Masthead";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../medlem.module.css";
import { MembershipFormCard } from "./MembershipFormCard";
import { OversiktCard } from "./OversiktCard";
import { PersonsCard } from "./PersonsCard";
import type { MembershipDetail } from "../types";

export const dynamic = "force-dynamic";

// Same mapping as the profil page's STATUS_BADGE: skog Aktiv /
// default Inaktiv / warning Väntar / himmel Friexemplar.
const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  active: { label: "Aktiv", className: "sb-badge sb-badge-skog" },
  inactive: { label: "Inaktiv", className: "sb-badge" },
  pending: { label: "Väntar", className: `sb-badge ${styles.badgeWarning}` },
  friexemplar: { label: "Friexemplar", className: "sb-badge sb-badge-himmel" },
};

export default async function MembershipDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let membership: MembershipDetail;
  try {
    membership = await fetchApi<MembershipDetail>(`/v2/members/${id}`);
  } catch (err) {
    // Only 404 should trigger notFound; other errors bubble to the
    // Next.js error boundary (same rule as the ansökningar detail page).
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  const user = await getUser();
  // Edit affordances: admin or matrikel_admin only — managers read-only.
  const canEdit = Boolean(user?.is_admin) || Boolean(user?.is_matrikel_admin);

  const main = membership.persons.find(
    (p) => p.role === "huvudmedlem" && p.end_date === null,
  );
  const badge = STATUS_BADGE[membership.membership_status] ?? {
    label: membership.membership_status,
    className: "sb-badge",
  };

  return (
    <>
      <Masthead
        eyebrow="Matrikel"
        title={
          membership.member_number
            ? `Medlemskap nr ${membership.member_number}`
            : "Medlemskap (utan nummer)"
        }
        meta={
          <>
            <span className={badge.className}>{badge.label}</span>
            <span>
              Huvudmedlem {main ? `${main.first_name} ${main.last_name}` : "–"}{" "}
              · medlem sedan {membership.joined_date ?? "–"}
            </span>
          </>
        }
      />
      <div className={styles.container}>
        <Link href="/medlem/matrikel" className={ds["ad-back"]}>
          ← Matrikel
        </Link>
        {/* Full bredd i stället för .ad-detail-grid: persontabellens sex
            kolumner behöver ~1100px för att inte radbrytas på desktop, och
            Översikt blir en statusremsa ovanför (samma recept som
            /medlem/statistik). */}
        <OversiktCard membership={membership} />
        <div className={ds["ad-col"]}>
          <PersonsCard membership={membership} canEdit={canEdit} />
          {canEdit ? <MembershipFormCard membership={membership} /> : null}
        </div>
      </div>
    </>
  );
}
