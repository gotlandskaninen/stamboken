"use client";

import { useState } from "react";
import Link from "next/link";
import { MenuItem, TextField } from "@mui/material";
import {
  fieldLabel,
  operationLabel,
  rowTitle,
  tableLabel,
} from "../../_lib/auditLabels";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";

export interface AuditRow {
  id: number;
  table_name: string;
  record_id: string;
  operation: string;
  old_data: unknown;
  new_data: unknown;
  // SYSTEM-markörer (massutloggning) skriver NULL —
  // app/utils/data_access.py:4159-4165.
  changed_fields: string[] | null;
  changed_by: string;
  changed_at: string;
}

// Alla 12 tabeller i AUDITED_TABLES (app/utils/database.py:2434-2451) plus
// audit_log — annars är rader från de sex saknade tabellerna oåtkomliga via
// filtret. Etiketterna kommer från TABLE_LABELS.
const TABLES = [
  "individual",
  "breeding",
  "bunny",
  "herd",
  "herd_tracking",
  "weight",
  "bodyfat",
  "individualdisease",
  "color",
  "hbuser",
  "genebank",
  "authenticators",
  "audit_log",
];

function asRecord(v: unknown): Record<string, unknown> | null {
  return typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : null;
}

// Ja/Nej för booleaner, tankstreck för tomt — motsvarar adFmtValue i
// stamboken-drift:docs/design/design_handoff_admin/surfaces/admin-ui.jsx:23.
function fmtValue(v: unknown): string {
  if (v === null || v === undefined || v === "") return "—";
  if (v === true) return "Ja";
  if (v === false) return "Nej";
  return String(v);
}

// surfaces/admin-ui.jsx:15-20. DELETE använder modulklassen; SYSTEM/REDACT
// får den neutrala .sb-badge.
const OP_BADGE: Record<string, string> = {
  INSERT: "sb-badge-mossa",
  UPDATE: "sb-badge-himmel",
};

function opBadgeClass(op: string): string {
  if (op === "DELETE") return styles["ad-badge-danger"];
  return OP_BADGE[op] ?? "";
}

function Row({ row }: { row: AuditRow }) {
  const [open, setOpen] = useState(false);
  const [raw, setRaw] = useState(false);
  const oldData = asRecord(row.old_data);
  const newData = asRecord(row.new_data);
  // UPDATE: backendens changed_fields är facit. INSERT/DELETE: nycklarna i
  // den kvarvarande ögonblicksbilden. SYSTEM-markörer har varken eller.
  const changed = row.changed_fields ?? [];
  const fields =
    changed.length > 0 ? changed : Object.keys(newData ?? oldData ?? {});
  const isSystem = row.operation === "SYSTEM" || fields.length === 0;
  return (
    <div
      className={
        open
          ? `${styles["ad-audit-row"]} ${styles["is-open"]}`
          : styles["ad-audit-row"]
      }
    >
      {/* Klickytan ÄR knappen — den gamla <Box onClick> saknade roll,
          tabindex och aria-expanded. Ingen interaktiv nästling: rådata-
          knappen ligger i detaljpanelen, utanför summary-knappen. */}
      <button
        type="button"
        className={styles["ad-audit-summary"]}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className={`sb-badge ${opBadgeClass(row.operation)}`}>
          {operationLabel(row.operation)}
        </span>
        {/* Hela radtiteln i EN sammanhängande textnod — textbaserade
            e2e-selektorer (14:72-73) hänger på det. */}
        <span className={styles["ad-audit-title"]}>
          {rowTitle(row.table_name, row.record_id)}
        </span>
        <span className={styles["ad-audit-fields"]}>
          {fields.map((f) => (
            <span key={f} className={styles["ad-field-chip"]}>
              {fieldLabel(f)}
            </span>
          ))}
        </span>
        <span className={`sb-meta ${styles["ad-audit-meta"]}`}>
          {row.changed_by} ·{" "}
          {new Date(row.changed_at).toLocaleString("sv-SE", {
            timeZone: "Europe/Stockholm",
          })}
        </span>
        <span
          className={
            open
              ? `${styles["ad-caret"]} ${styles["is-open"]}`
              : styles["ad-caret"]
          }
          aria-hidden="true"
        >
          ›
        </span>
      </button>
      {open && (
        <div className={styles["ad-audit-detail"]}>
          {isSystem ? (
            <p className={ds["ad-hint"]}>
              Systemhändelse utförd av {row.changed_by}.{" "}
              {typeof newData?.sessions_cleared === "number"
                ? `${newData.sessions_cleared} sessioner avslutades.`
                : "Ingen post ändrades."}
            </p>
          ) : (
            <>
              <div className={styles["ad-diff-scroll"]}>
                <table className={styles["ad-diff"]}>
                  <thead>
                    <tr>
                      <th>Fält</th>
                      {oldData && <th>Före</th>}
                      {oldData && newData && <th aria-hidden="true" />}
                      {newData && <th>Efter</th>}
                    </tr>
                  </thead>
                  <tbody>
                    {fields.map((f) => (
                      <tr key={f}>
                        <td className={styles["ad-diff-field"]}>
                          {fieldLabel(f)}
                        </td>
                        {oldData && (
                          <td>
                            <span className={styles["ad-diff-old"]}>
                              {fmtValue(oldData[f])}
                            </span>
                          </td>
                        )}
                        {oldData && newData && (
                          <td
                            className={styles["ad-diff-arrow"]}
                            aria-hidden="true"
                          >
                            →
                          </td>
                        )}
                        {newData && (
                          <td>
                            <span className={styles["ad-diff-new"]}>
                              {fmtValue(newData[f])}
                            </span>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {/* Rådata är aldrig förvalt läge (README rad 53). */}
              <button
                type="button"
                className={`sb-btn sb-btn-ghost sb-btn-sm ${styles["ad-raw-toggle"]}`}
                onClick={() => setRaw(!raw)}
              >
                {raw ? "Dölj rådata" : "Visa rådata"}
              </button>
              {raw && (
                <div className={styles["ad-raw"]}>
                  <div>
                    <div className="sb-meta">Före ändringen</div>
                    <pre className={styles["ad-pre"]}>
                      {JSON.stringify(row.old_data ?? {}, null, 2)}
                    </pre>
                  </div>
                  <div>
                    <div className="sb-meta">Efter ändringen</div>
                    <pre className={styles["ad-pre"]}>
                      {JSON.stringify(row.new_data ?? {}, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}

export function AuditLogClient({
  rows,
  total,
  page,
  perPage,
  filters,
}: {
  rows: AuditRow[];
  total: number;
  page: number;
  perPage: number;
  filters: {
    table: string;
    record_id: string;
    changed_by: string;
    from: string;
    to: string;
    op: string;
  };
}) {
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const pageHref = (p: number) => {
    const qs = new URLSearchParams();
    for (const [k, v] of Object.entries(filters)) if (v) qs.set(k, v);
    qs.set("page", String(p));
    return `/stamboken/admin/system/audit?${qs.toString()}`;
  };
  return (
    <>
      <p className={ds["ad-hint"]}>
        Loggen visar alla ändringar i databasen — vad som ändrades, av vem och
        när. Öppna en rad för att se varje fält före och efter ändringen.
      </p>
      <div className={`sb-card ${ds["ad-grid"]}`}>
        {/* Native GET — MUI:s TextField/TextField-select måste behålla sina
            name-attribut (table/record_id/changed_by/from/to/op), annars
            nollställs filtret tyst vid submit. Temat styr kontrollerna. */}
        <form method="get" className={ds["ad-grid-toolbar"]}>
          <TextField
            select
            name="table"
            label="Område"
            defaultValue={filters.table}
            size="small"
            sx={{ minWidth: 170 }}
          >
            <MenuItem value="">Alla</MenuItem>
            {TABLES.map((t) => (
              <MenuItem key={t} value={t}>
                {tableLabel(t)}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            name="record_id"
            label="Postens id"
            defaultValue={filters.record_id}
            size="small"
          />
          <TextField
            name="changed_by"
            label="Utförd av"
            defaultValue={filters.changed_by}
            size="small"
          />
          <TextField
            name="from"
            label="Från"
            type="date"
            defaultValue={filters.from}
            size="small"
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <TextField
            name="to"
            label="Till"
            type="date"
            defaultValue={filters.to}
            size="small"
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <TextField
            select
            name="op"
            label="Åtgärd"
            defaultValue={filters.op}
            size="small"
            sx={{ minWidth: 140 }}
          >
            <MenuItem value="">Alla</MenuItem>
            <MenuItem value="INSERT">Skapad</MenuItem>
            <MenuItem value="UPDATE">Ändrad</MenuItem>
            <MenuItem value="DELETE">Borttagen</MenuItem>
            <MenuItem value="SYSTEM">Systemhändelse</MenuItem>
            <MenuItem value="REDACT">Gallring</MenuItem>
          </TextField>
          <button type="submit" className="sb-btn sb-btn-secondary sb-btn-sm">
            Filtrera
          </button>
        </form>
        <div>
          {rows.map((r) => (
            <Row key={r.id} row={r} />
          ))}
          {rows.length === 0 && (
            <p className={ds["ad-empty-note"]}>
              Inga händelser matchar filtret.
            </p>
          )}
        </div>
        <div className={ds["ad-grid-foot"]}>
          <span className="sb-meta">{total} händelser</span>
          <span className={ds["ad-grid-spacer"]} />
          {totalPages > 1 && (
            <>
              <span className="sb-meta">
                Sida {page} av {totalPages}
              </span>
              {page > 1 && (
                <Link
                  href={pageHref(page - 1)}
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                >
                  Föregående
                </Link>
              )}
              {page < totalPages && (
                <Link
                  href={pageHref(page + 1)}
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                >
                  Nästa
                </Link>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
