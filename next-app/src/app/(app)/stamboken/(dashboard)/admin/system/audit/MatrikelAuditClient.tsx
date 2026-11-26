"use client";

import { useState } from "react";
import Link from "next/link";
import { MenuItem, TextField } from "@mui/material";
import {
  MATRIKEL_ACTION_LABELS,
  formatAuditTime,
  matrikelActionLabel,
  matrikelChangedFields,
  matrikelFieldLabel,
  matrikelValue,
} from "../../_lib/auditLabels";
import type { MatrikelAuditRow } from "@/app/(app)/medlem/matrikel/types";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";

export type MatrikelFilters = {
  action: string;
  actor: string;
  member_number: string;
  /** Set only by the member page's link for a membership without a number. */
  membership_id: string;
  from: string;
  to: string;
};

export function matrikelRowTitle(row: MatrikelAuditRow): string {
  const ms = row.membership.member_number
    ? `Medlemskap nr ${row.membership.member_number}`
    : `Medlemskap #${row.membership.id}`;
  return row.person
    ? `${ms} · ${row.person.name || `Person #${row.person.id}`}`
    : ms;
}

const asRecord = (v: unknown): Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v)
    ? (v as Record<string, unknown>)
    : {};

function Detail({ row }: { row: MatrikelAuditRow }) {
  // "fields" (names only) is already in the summary's chips.
  const { before, after, fields: _fields, ...rest } = row.payload;
  const hasDiff = before !== undefined || after !== undefined;
  // The diff table only for fields with values; names alone are the summary's chips.
  const changed = matrikelChangedFields(row.payload).filter(
    (f) => f in asRecord(before) || f in asRecord(after),
  );
  return (
    <div className={styles["ad-audit-detail"]}>
      <p className={ds["ad-hint"]}>
        {row.actor?.id ? (
          <>
            Utförd av{" "}
            <Link href={`/stamboken/admin/anvandare/${row.actor.id}`}>
              {row.actor.name}
            </Link>
          </>
        ) : row.actor ? (
          `Utförd av ${row.actor.name}`
        ) : (
          "Utförd av den nattliga gallringen"
        )}{" "}
        ·{" "}
        <Link href={`/medlem/matrikel/${row.membership.id}`}>
          Öppna medlemskapet
        </Link>
      </p>
      {hasDiff && (
        <div className={styles["ad-diff-scroll"]}>
          <table className={styles["ad-diff"]}>
            <thead>
              <tr>
                <th>Fält</th>
                <th>Före</th>
                <th aria-hidden="true" />
                <th>Efter</th>
              </tr>
            </thead>
            <tbody>
              {changed.map((f) => (
                <tr key={f}>
                  <td className={styles["ad-diff-field"]}>
                    {matrikelFieldLabel(f)}
                  </td>
                  <td>
                    <span className={styles["ad-diff-old"]}>
                      {matrikelValue(f, asRecord(before)[f])}
                    </span>
                  </td>
                  <td className={styles["ad-diff-arrow"]} aria-hidden="true">
                    →
                  </td>
                  <td>
                    <span className={styles["ad-diff-new"]}>
                      {matrikelValue(f, asRecord(after)[f])}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {Object.keys(rest).length > 0 && (
        <dl className={ds["ad-kv"]}>
          {Object.entries(rest).map(([k, v]) => (
            <div key={k}>
              <dt>{matrikelFieldLabel(k)}</dt>
              <dd>{matrikelValue(k, v)}</dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  );
}

function Row({ row }: { row: MatrikelAuditRow }) {
  const [open, setOpen] = useState(false);
  return (
    <div
      className={
        open
          ? `${styles["ad-audit-row"]} ${styles["is-open"]}`
          : styles["ad-audit-row"]
      }
    >
      <button
        type="button"
        className={styles["ad-audit-summary"]}
        aria-expanded={open}
        onClick={() => setOpen(!open)}
      >
        <span className="sb-badge">{matrikelActionLabel(row.action)}</span>
        <span className={styles["ad-audit-title"]}>
          {matrikelRowTitle(row)}
        </span>
        <span className={styles["ad-audit-fields"]}>
          {matrikelChangedFields(row.payload).map((f) => (
            <span key={f} className={styles["ad-field-chip"]}>
              {matrikelFieldLabel(f)}
            </span>
          ))}
        </span>
        <span className={`sb-meta ${styles["ad-audit-meta"]}`}>
          {row.actor?.name ?? "Nattlig gallring"} ·{" "}
          {formatAuditTime(row.created_at)}
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
      {open && <Detail row={row} />}
    </div>
  );
}

export function MatrikelAuditClient({
  rows,
  total,
  page,
  perPage,
  filters,
}: {
  rows: MatrikelAuditRow[];
  total: number;
  page: number;
  perPage: number;
  filters: MatrikelFilters;
}) {
  const totalPages = Math.max(1, Math.ceil(total / perPage));
  const pageHref = (p: number) => {
    const qs = new URLSearchParams({ source: "matrikel" });
    for (const [k, v] of Object.entries(filters)) if (v) qs.set(k, v);
    qs.set("page", String(p));
    return `/stamboken/admin/system/audit?${qs.toString()}`;
  };
  return (
    <>
      <p className={ds["ad-hint"]}>
        Matrikelns ändringar — medlemskap, personer, konton och åtkomster. Öppna
        en rad för att se vad som ändrades. Uppgifter om anonymiserade personer
        visas som [borttagen].
      </p>
      <div className={`sb-card ${ds["ad-grid"]}`}>
        <form method="get" className={ds["ad-grid-toolbar"]}>
          <input type="hidden" name="source" value="matrikel" />
          {filters.membership_id && !filters.member_number && (
            <input
              type="hidden"
              name="membership_id"
              value={filters.membership_id}
            />
          )}
          <TextField
            select
            name="action"
            label="Åtgärd"
            defaultValue={filters.action}
            size="small"
            sx={{ minWidth: 200 }}
          >
            <MenuItem value="">Alla</MenuItem>
            {Object.entries(MATRIKEL_ACTION_LABELS).map(([value, label]) => (
              <MenuItem key={value} value={value}>
                {label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            name="actor"
            label="Utförd av"
            defaultValue={filters.actor}
            size="small"
            helperText="Användarnamn eller e-post"
          />
          <TextField
            name="member_number"
            label="Medlemsnummer"
            defaultValue={filters.member_number}
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
