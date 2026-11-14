import Link from "next/link";
import { Alert } from "@mui/material";
import { fetchApi } from "@/lib/api";
import { requireHerdAdmin } from "../_lib/requireAdmin";
import { Alarms } from "./Alarms";
import { RowActions } from "./RowActions";
import { formatTime, STATUS_LABEL, statusLabel, type MailList } from "./lib";
import ds from "@/styles/ds-admin.module.css";
import admin from "../admin.module.css";
import styles from "./utskick.module.css";

export const dynamic = "force-dynamic";

const PATH = "/stamboken/admin/utskick";
const LIMIT = 50;
const FILTER_KEYS = ["status", "kind", "from", "to"] as const;

const badgeClass = (s: string) =>
  s === "sent"
    ? "sb-badge sb-badge-mossa"
    : s === "failed" || s === "bounced" || s === "blocked"
      ? `sb-badge ${admin["ad-badge-danger"]}`
      : "sb-badge";

export default async function UtskickPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  await requireHerdAdmin(); // Page-level gate, layout renders concurrently
  const sp = await searchParams;
  const filters = new URLSearchParams();
  for (const k of FILTER_KEYS) if (sp[k]) filters.set(k, sp[k] as string);
  const offset = /^\d+$/.test(sp.offset ?? "") ? Number(sp.offset) : 0;

  // The API has no total: ask for one row more to know if a next page exists.
  const api = new URLSearchParams(filters);
  api.set("limit", String(LIMIT + 1));
  api.set("offset", String(offset));
  let data: MailList | null = null;
  try {
    data = await fetchApi<MailList>(`/v2/mail/messages?${api}`, {
      forceProd: true,
    });
  } catch {
    data = null;
  }

  const pageHref = (o: number) => {
    const q = new URLSearchParams(filters);
    if (o > 0) q.set("offset", String(o));
    return `${PATH}?${q}`;
  };

  return (
    <>
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>Utskick</h2>
      </div>
      {data === null ? (
        <Alert severity="error">
          Kunde inte läsa utskicken just nu. Försök igen om en stund.
        </Alert>
      ) : (
        <>
          <Alarms data={data} />
          <section className={`sb-card ${ds["ad-grid"]}`}>
            <form method="get" action={PATH} className={ds["ad-grid-toolbar"]}>
              <label className={ds["ad-filter"]}>
                <span className={ds["ad-filter-label"]}>Status</span>
                <select
                  name="status"
                  defaultValue={sp.status ?? ""}
                  className="sb-input"
                >
                  <option value="">Alla</option>
                  {Object.entries(STATUS_LABEL).map(([v, l]) => (
                    <option key={v} value={v}>
                      {l}
                    </option>
                  ))}
                </select>
              </label>
              <label className={ds["ad-filter"]}>
                <span className={ds["ad-filter-label"]}>Typ</span>
                <input
                  type="text"
                  name="kind"
                  defaultValue={sp.kind ?? ""}
                  className="sb-input"
                />
              </label>
              <label className={ds["ad-filter"]}>
                <span className={ds["ad-filter-label"]}>Från</span>
                <input
                  type="date"
                  name="from"
                  defaultValue={sp.from ?? ""}
                  className="sb-input"
                />
              </label>
              <label className={ds["ad-filter"]}>
                <span className={ds["ad-filter-label"]}>Till</span>
                <input
                  type="date"
                  name="to"
                  defaultValue={sp.to ?? ""}
                  className="sb-input"
                />
              </label>
              <button type="submit" className="sb-btn sb-btn-sm">
                Filtrera
              </button>
            </form>

            {data.items.length === 0 ? (
              <p className={ds["ad-empty-note"]}>
                Inga utskick matchar filtren.
              </p>
            ) : (
              <table className={styles.table}>
                <thead>
                  <tr>
                    <th>Skapad</th>
                    <th>Typ</th>
                    <th>Mottagare</th>
                    <th>Status</th>
                    <th>Försök</th>
                    <th>Senaste fel</th>
                    <th>Åtgärd</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.slice(0, LIMIT).map((m) => (
                    <tr key={m.id}>
                      <td data-label="Skapad">{formatTime(m.created_at)}</td>
                      <td data-label="Typ" className={ds["ad-cell-mono"]}>
                        {m.kind}
                      </td>
                      <td data-label="Mottagare">{m.recipient}</td>
                      <td>
                        <span className={badgeClass(m.status)}>
                          {statusLabel(m.status)}
                        </span>
                      </td>
                      <td data-label="Försök">{m.attempts}</td>
                      <td className={styles.error}>{m.last_error ?? ""}</td>
                      <td>
                        <RowActions id={m.id} status={m.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            <div className={ds["ad-grid-foot"]}>
              <span className={ds["ad-grid-spacer"]} />
              {offset > 0 && (
                <Link
                  href={pageHref(Math.max(0, offset - LIMIT))}
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                >
                  Föregående
                </Link>
              )}
              {data.items.length > LIMIT && (
                <Link
                  href={pageHref(offset + LIMIT)}
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                >
                  Nästa
                </Link>
              )}
            </div>
          </section>
        </>
      )}
    </>
  );
}
