"use client";

import React from "react";
import {
  KIND_LABELS,
  PERIOD_START_LABELS,
  type HerdTrackingHistory,
  type HerdTrackingRow,
} from "@/lib/herdTracking";
import styles from "./HerdHistorySection.module.css";

interface HerdHistorySectionProps {
  history: HerdTrackingHistory | null;
  onVoid?: (row: HerdTrackingRow) => void;
  onUndoOperation?: (row: HerdTrackingRow) => void;
  onCorrect?: () => void;
}

const HEADING_ID = "herd-history-heading";

/** Periods by default, the raw event list behind "Visa allt" — in server order, never re-sorted. */
export function HerdHistorySection({
  history,
  onVoid,
  onUndoOperation,
  onCorrect,
}: HerdHistorySectionProps) {
  const [showAll, setShowAll] = React.useState(false);
  // "Visa ångrade" is off for owners, on for genebank managers/admin.
  const [showVoided, setShowVoided] = React.useState(
    history?.viewer.can_manage ?? false,
  );

  const heading = (
    <h2 id={HEADING_ID} className="sb-h6">
      Besättningshistorik
    </h2>
  );

  if (!history) {
    return (
      <section
        className={`sb-card ${styles.section}`}
        aria-labelledby={HEADING_ID}
      >
        {heading}
        <p className="sb-meta">Besättningshistoriken kunde inte hämtas.</p>
      </section>
    );
  }
  // Managers can add missing history even when there is none yet.
  const correctButton = history.viewer.can_manage && onCorrect && (
    <button
      type="button"
      className="sb-btn sb-btn-secondary sb-btn-sm"
      onClick={onCorrect}
    >
      Korrigera historik
    </button>
  );

  if (history.rows.length === 0) {
    return (
      <section
        className={`sb-card ${styles.section}`}
        aria-labelledby={HEADING_ID}
      >
        <div className={styles.header}>
          {heading}
          {correctButton}
        </div>
        <p className="sb-meta">Ingen besättningshistorik registrerad.</p>
      </section>
    );
  }

  const periods = [...history.periods].reverse();
  const rows = history.rows.filter((r) => showVoided || r.voided_at === null);

  return (
    <section
      className={`sb-card ${styles.section}`}
      aria-labelledby={HEADING_ID}
    >
      <div className={styles.header}>
        {heading}
        {correctButton}
      </div>

      {showAll ? (
        <>
          <label className={styles.toggle}>
            <input
              type="checkbox"
              checked={showVoided}
              onChange={(e) => setShowVoided(e.target.checked)}
            />
            Visa ångrade
          </label>
          {rows.length === 0 ? (
            <p className="sb-meta">Ingen besättningshistorik registrerad.</p>
          ) : (
            <ol className={styles.list} aria-label="Alla händelser">
              {rows.map((row) => (
                <li
                  key={row.id}
                  data-testid="ht-row"
                  className={
                    row.voided_at
                      ? `${styles.row} ${styles.voided}`
                      : styles.row
                  }
                >
                  <span className="sb-meta">{row.date}</span>
                  <span>{KIND_LABELS[row.kind]}</span>
                  <span>{row.herd.label}</span>
                  {row.voided_at && <span className="sb-badge">Ångrad</span>}
                  {row.confirmed === false && (
                    <span className="sb-badge sb-badge-lera">ej bekräftad</span>
                  )}
                  {row.buyer && (
                    <span className="sb-meta">
                      Köpare: {row.buyer.name}, {row.buyer.town}
                    </span>
                  )}
                  {row.voided_reason && (
                    <span className="sb-meta">{row.voided_reason}</span>
                  )}
                  {row.notes && <span className="sb-meta">{row.notes}</span>}
                  <span className={styles.actions}>
                    {row.can_void && onVoid && (
                      <button
                        type="button"
                        className="sb-btn sb-btn-ghost sb-btn-sm"
                        onClick={() => onVoid(row)}
                      >
                        Ångra
                      </button>
                    )}
                    {row.can_undo_operation && onUndoOperation && (
                      <button
                        type="button"
                        className="sb-btn sb-btn-ghost sb-btn-sm"
                        onClick={() => onUndoOperation(row)}
                      >
                        Ångra hela åtgärden
                      </button>
                    )}
                  </span>
                </li>
              ))}
            </ol>
          )}
        </>
      ) : (
        <ol className={styles.list} aria-label="Perioder">
          {periods.map((period) => {
            const reports = period.attestation_ids.length;
            return (
              <li
                key={period.start_row_id}
                data-testid="ht-period"
                className={styles.row}
              >
                <span>{period.herd.label}</span>
                <span className="sb-meta">
                  {period.from_date} – {period.to_date ?? "nu"}
                </span>
                <span className="sb-meta">
                  {PERIOD_START_LABELS[period.start_kind]}
                  {reports > 0
                    ? ` · ${reports} ${reports === 1 ? "årsrapport" : "årsrapporter"}`
                    : ""}
                </span>
              </li>
            );
          })}
        </ol>
      )}

      <button
        type="button"
        className="sb-btn sb-btn-ghost sb-btn-sm"
        aria-expanded={showAll}
        onClick={() => setShowAll(!showAll)}
      >
        {showAll ? "Visa perioder" : "Visa allt"}
      </button>
    </section>
  );
}
