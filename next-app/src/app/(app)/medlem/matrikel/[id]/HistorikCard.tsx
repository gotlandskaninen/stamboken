import Link from "next/link";
import {
  formatAuditTime,
  matrikelActionLabel,
  matrikelChangedFields,
  matrikelFieldLabel,
} from "@/app/(app)/stamboken/(dashboard)/admin/_lib/auditLabels";
import ds from "@/styles/ds-admin.module.css";
import type { MatrikelAuditPage } from "../types";

/**
 * De senaste händelserna i matrikelns logg för medlemskapet och dess personer
 * (#244). Hela listan ligger i aktivitetsloggen, som bara admin når — därför
 * länkarna bara för admin.
 */
export function HistorikCard({
  membershipId,
  history,
  isAdmin,
}: {
  membershipId: number;
  /** null: loggen gick inte att läsa. */
  history: MatrikelAuditPage | null;
  isAdmin: boolean;
}) {
  return (
    <section className="sb-card">
      <div className={ds["ad-card-head"]}>
        <h3 className={`sb-h6 ${ds["ad-card-title"]}`}>Historik</h3>
        {isAdmin && history && history.total > 0 ? (
          <Link
            href={`/stamboken/admin/system/audit?source=matrikel&membership_id=${membershipId}`}
            className="sb-btn sb-btn-ghost sb-btn-sm"
          >
            Visa hela historiken ({history.total})
          </Link>
        ) : null}
      </div>
      <div className={ds["ad-card-body"]}>
        {history === null ? (
          <p className={ds["ad-hint"]}>Historiken kunde inte läsas just nu.</p>
        ) : history.rows.length === 0 ? (
          <p className={ds["ad-hint"]}>Inga ändringar är loggade ännu.</p>
        ) : (
          <dl className={ds["ad-kv"]}>
            {history.rows.map((row) => {
              const fields = matrikelChangedFields(row.payload)
                .map(matrikelFieldLabel)
                .join(", ");
              return (
                <div key={row.id}>
                  <dt>
                    {formatAuditTime(row.created_at)} ·{" "}
                    {row.actor === null ? (
                      "nattlig gallring"
                    ) : isAdmin ? (
                      <Link href={`/stamboken/admin/anvandare/${row.actor.id}`}>
                        {row.actor.name}
                      </Link>
                    ) : (
                      row.actor.name
                    )}
                  </dt>
                  <dd>
                    {matrikelActionLabel(row.action)}
                    {row.person
                      ? ` · ${row.person.name || `Person #${row.person.id}`}`
                      : ""}
                    {fields ? ` — ${fields}` : ""}
                  </dd>
                </div>
              );
            })}
          </dl>
        )}
      </div>
    </section>
  );
}
