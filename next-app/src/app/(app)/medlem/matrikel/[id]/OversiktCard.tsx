import Link from "next/link";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../medlem.module.css";
import type { MembershipDetail } from "../types";
import { KopplaBesattningButton } from "./KopplaBesattningDialog";

// Spec-copy for the publiceringsval (matrikel label "Publiceras i Koharen").
const CONSENT_LABELS: Record<string, string> = {
  name: "namn",
  phone: "telefon",
  email: "e-post",
  address: "adress",
};

function Cell({
  label,
  children,
  action,
}: {
  label: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className={`${ds["ad-status-cell"]} ${styles.ovCell}`}>
      <div className={styles.ovVal}>{children}</div>
      <div className="sb-stat-label">{label}</div>
      {action}
    </div>
  );
}

/**
 * Översikt som statusremsa ovanför persontabellen (statistik-sidans
 * .ad-status-strip). Huvudmedlem och "medlem sedan" står redan i mastheadens
 * meta-rad, så remsan bär bara det som inte syns någon annanstans — fyra
 * celler, vilket är precis remsans desktopkolumner.
 */
export function OversiktCard({
  membership,
  canEdit,
  canOpenHerd = () => false,
}: {
  membership: MembershipDetail;
  canEdit: boolean;
  /** Whether the reader may open the herd's admin page (admin, or manager of its genebank). */
  canOpenHerd?: (genebankId: number) => boolean;
}) {
  const consent =
    Object.entries(membership.publication_consent)
      .filter(([, v]) => v)
      .map(([k]) => CONSENT_LABELS[k] ?? k)
      .join(", ") || "inget";
  const linked = membership.persons.filter((p) => p.user).length;

  return (
    <section
      className={`sb-card ${ds["ad-status-strip"]}`}
      aria-label="Översikt"
    >
      {/* Read-only managers never see MembershipFormCard, so the payment
          note has to live here too (it did in the pre-reskin summary). */}
      <Cell label="Betalningsnotering">{membership.payment_note || "–"}</Cell>
      <Cell label="Publiceras i Koharen">{consent}</Cell>
      <Cell
        label="Besättningar"
        action={
          canEdit && <KopplaBesattningButton membershipId={membership.id} />
        }
      >
        {membership.herds.length === 0 ? (
          "inga"
        ) : (
          <span className={styles.badgeRow}>
            {membership.herds.map((h) => {
              // The herd's own status in words: green alone read as "aktiv" for every linked herd (#214).
              const label = `${h.herd_name ? `${h.herd} — ${h.herd_name}` : h.herd} · ${h.is_active ? "aktiv" : "inaktiv"}`;
              const className = `sb-badge${h.is_active ? " sb-badge-mossa" : ""}`;
              return canOpenHerd(h.genebank_id) ? (
                <Link
                  key={h.id}
                  href={`/stamboken/admin/besattningar/${h.herd}`}
                  className={className}
                >
                  {label}
                </Link>
              ) : (
                <span key={h.id} className={className}>
                  {label}
                </span>
              );
            })}
          </span>
        )}
      </Cell>
      <Cell label="Kopplade konton">{`${linked} av ${membership.persons.length} personer`}</Cell>
    </section>
  );
}
