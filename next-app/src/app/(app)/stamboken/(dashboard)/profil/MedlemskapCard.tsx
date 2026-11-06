import Link from "next/link";
import type { Me, MyHerd } from "./types";
import { ROLE_LABELS, STATUS_BADGE } from "./types";
import styles from "./profil.module.css";

export function MedlemskapCard({ me, herds }: { me: Me; herds: MyHerd[] }) {
  const ms = me.membership;
  const badge = STATUS_BADGE[ms.membership_status] ?? {
    label: ms.membership_status,
    className: "sb-badge",
  };
  const className = badge.className.replace(
    "badgeWarning",
    styles.badgeWarning,
  );
  return (
    <section className="sb-card">
      <div className={styles.cardHead}>
        <h3 className={`sb-h6 ${styles.cardTitle}`}>Medlemskap</h3>
        <span className={className}>{badge.label}</span>
      </div>
      <div className={styles.cardBody}>
        <dl className={styles.kv}>
          <div>
            <dt>Medlemsnummer</dt>
            <dd className={styles.mono}>{ms.member_number ?? "–"}</dd>
          </div>
          <div>
            <dt>Medlem sedan</dt>
            <dd>{ms.joined_date ?? "–"}</dd>
          </div>
          <div>
            <dt>Huvudmedlem</dt>
            <dd>{me.main_member_name ?? "–"}</dd>
          </div>
          <div>
            <dt>Din roll</dt>
            <dd>{ROLE_LABELS[me.role]}</dd>
          </div>
        </dl>
        <hr className={`sb-rule ${styles.rule}`} />
        <div className={styles.badgeRow}>
          <span className="sb-meta">Besättningar</span>
          {herds.length === 0 && (
            <span className={styles.hint} style={{ margin: 0 }}>
              inga
            </span>
          )}
          {herds.map((h) => (
            <Link
              key={h.id}
              href={`/stamboken/min-besattning?herd=${h.herd}`}
              className="sb-badge sb-badge-mossa"
            >
              {h.herd_name ? `${h.herd} — ${h.herd_name}` : h.herd}
            </Link>
          ))}
          {herds.length > 0 && (
            <Link href="/stamboken/min-besattning" className="sb-link">
              Öppna i Min besättning
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}
