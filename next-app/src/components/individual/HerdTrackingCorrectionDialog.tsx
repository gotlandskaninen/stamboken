"use client";

import React from "react";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import type { GenebankHerd } from "@/utils/saleRules";
import {
  KIND_LABELS,
  newOperationId,
  type HerdTrackingHistory,
  type HerdTrackingKind,
} from "@/lib/herdTracking";
import { BUYER_PRIVACY_HELP, htErrorMessage } from "./VoidHerdTrackingDialog";
import styles from "./HerdTrackingCorrectionDialog.module.css";

export interface CorrectionEvent {
  date: string;
  herd: string;
  kind: HerdTrackingKind;
  notes: string | null;
}

export interface CorrectionPayload {
  operation_id: string;
  void_ids: number[];
  events: CorrectionEvent[];
  reason: string;
}

type LoadHerdsResult =
  | { success: true; herds: GenebankHerd[] }
  | { success: false; error: string };

interface Props {
  open: boolean;
  history: HerdTrackingHistory;
  loadHerds: () => Promise<LoadHerdsResult>;
  busy: boolean;
  error: string | null;
  /** Row ids a 409 named: pre-checked for voiding so the manager can resave in one step. */
  conflictRowIds?: number[];
  onClose: () => void;
  onConfirm: (payload: CorrectionPayload) => void;
}

const EVENT_KINDS: HerdTrackingKind[] = [
  "TRANSFER",
  "CORRECTION",
  "ATTESTATION",
  "BIRTH",
];

export function isChronological(events: CorrectionEvent[]): boolean {
  return events.every((e, i) => i === 0 || events[i - 1].date <= e.date);
}

/**
 * Remounted per opening (fresh operation id, no stale rows).
 * (Twin of the wrapper in VoidHerdTrackingDialog — duplicated on purpose, a hook is not worth it.)
 */
export function HerdTrackingCorrectionDialog(props: Props) {
  const [openings, setOpenings] = React.useState(0);
  const [wasOpen, setWasOpen] = React.useState(props.open);
  if (props.open !== wasOpen) {
    setWasOpen(props.open);
    if (props.open) setOpenings((n) => n + 1);
  }
  return <CorrectionContent key={openings} {...props} />;
}

function CorrectionContent({
  open,
  history,
  loadHerds,
  busy,
  error,
  conflictRowIds,
  onClose,
  onConfirm,
}: Props) {
  const [operationId] = React.useState(newOperationId);
  const [voidIds, setVoidIds] = React.useState<number[]>([]);
  const activeRows = history.rows.filter((r) => r.voided_at === null);
  const [seenConflict, setSeenConflict] = React.useState(conflictRowIds);
  if (conflictRowIds !== seenConflict) {
    setSeenConflict(conflictRowIds);
    const add = activeRows
      .map((r) => r.id)
      .filter((id) => conflictRowIds?.includes(id) && !voidIds.includes(id));
    if (add.length) setVoidIds([...voidIds, ...add]);
  }
  const errorRef = React.useRef<HTMLParagraphElement>(null);
  React.useEffect(() => {
    // At 375 px the alert sits below the fold of the scrollable dialog.
    if (!error) return;
    errorRef.current?.scrollIntoView?.({ block: "nearest" });
    errorRef.current?.focus();
  }, [error]);
  const [events, setEvents] = React.useState<CorrectionEvent[]>([]);
  const [reason, setReason] = React.useState("");
  const [herds, setHerds] = React.useState<GenebankHerd[]>([]);
  const [herdsError, setHerdsError] = React.useState<string | null>(null);

  React.useEffect(() => {
    if (!open) return;
    let alive = true;
    loadHerds().then((result) => {
      if (!alive) return;
      if (result.success) setHerds(result.herds);
      else
        setHerdsError(
          result.error === "unexpected_error"
            ? "Kunde inte hämta besättningar."
            : result.error,
        );
    });
    return () => {
      alive = false;
    };
  }, [open, loadHerds]);

  const toggleVoid = (id: number) =>
    setVoidIds((ids) =>
      ids.includes(id) ? ids.filter((v) => v !== id) : [...ids, id],
    );
  const updateEvent = (index: number, patch: Partial<CorrectionEvent>) =>
    setEvents((list) =>
      list.map((e, i) => (i === index ? { ...e, ...patch } : e)),
    );

  const complete = events.every((e) => e.date && e.herd);
  const chronological = isChronological(events);
  const needsReason = voidIds.length > 0 && !reason.trim();
  const canSubmit =
    !busy &&
    (voidIds.length > 0 || events.length > 0) &&
    complete &&
    chronological &&
    !needsReason;

  return (
    <Dialog
      open={open}
      onClose={busy ? undefined : onClose}
      fullWidth
      maxWidth="md"
    >
      <DialogTitle>Korrigera historik</DialogTitle>
      <DialogContent>
        <fieldset className={styles.fieldset}>
          <legend className="sb-label">Händelser att ångra</legend>
          {activeRows.map((row) => (
            <label key={row.id} className={styles.check}>
              <input
                type="checkbox"
                checked={voidIds.includes(row.id)}
                onChange={() => toggleVoid(row.id)}
              />
              {`${row.date} · ${KIND_LABELS[row.kind]} · ${row.herd.label}`}
            </label>
          ))}
        </fieldset>

        <fieldset className={`${styles.fieldset} ${styles.fieldsetSpaced}`}>
          <legend className="sb-label">Nya händelser (i tidsordning)</legend>
          {events.map((event, index) => (
            <div key={index} className={styles.event}>
              <label className="sb-label">
                Datum
                <input
                  type="date"
                  className="sb-input"
                  value={event.date}
                  onChange={(e) => updateEvent(index, { date: e.target.value })}
                />
              </label>
              <label className="sb-label">
                Besättning
                <select
                  className="sb-input"
                  value={event.herd}
                  onChange={(e) => updateEvent(index, { herd: e.target.value })}
                >
                  <option value="">Välj besättning</option>
                  {herds.map((h) => (
                    <option key={h.herd} value={h.herd}>
                      {h.herd_name ? `${h.herd} – ${h.herd_name}` : h.herd}
                    </option>
                  ))}
                </select>
              </label>
              <label className="sb-label">
                Typ
                <select
                  className="sb-input"
                  value={event.kind}
                  onChange={(e) =>
                    updateEvent(index, {
                      kind: e.target.value as HerdTrackingKind,
                    })
                  }
                >
                  {EVENT_KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {KIND_LABELS[kind]}
                    </option>
                  ))}
                </select>
              </label>
              <label className="sb-label">
                Anteckning
                <input
                  className="sb-input"
                  value={event.notes ?? ""}
                  onChange={(e) =>
                    updateEvent(index, { notes: e.target.value || null })
                  }
                />
              </label>
            </div>
          ))}
          {herdsError && (
            <p
              role="alert"
              className="sb-meta"
              style={{ color: "var(--sb-danger)" }}
            >
              {herdsError}
            </p>
          )}
          <button
            type="button"
            className={`sb-btn sb-btn-secondary sb-btn-sm ${styles.btn}`}
            onClick={() =>
              setEvents((list) => [
                ...list,
                { date: "", herd: "", kind: "TRANSFER", notes: null },
              ])
            }
          >
            Lägg till händelse
          </button>
          {!chronological && (
            <p className="sb-meta">Ange händelserna i tidsordning.</p>
          )}
        </fieldset>

        {/* The server stores the reason only for voided rows (and requires it then). */}
        {voidIds.length > 0 && (
          <>
            <label className="sb-label" htmlFor="ht-correction-reason">
              Anledning
            </label>
            <textarea
              id="ht-correction-reason"
              className="sb-input"
              rows={2}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </>
        )}
        <p className="sb-meta">{BUYER_PRIVACY_HELP}</p>
        {error && (
          <p
            ref={errorRef}
            role="alert"
            tabIndex={-1}
            className="sb-meta"
            style={{ color: "var(--sb-danger)" }}
          >
            {htErrorMessage(error)}
          </p>
        )}
      </DialogContent>
      <DialogActions>
        <button
          type="button"
          className={`sb-btn sb-btn-secondary sb-btn-sm ${styles.btn}`}
          onClick={onClose}
          disabled={busy}
        >
          Avbryt
        </button>
        <button
          type="button"
          className={`sb-btn sb-btn-sm ${styles.btn}`}
          disabled={!canSubmit}
          onClick={() =>
            onConfirm({
              operation_id: operationId,
              void_ids: voidIds,
              events,
              reason: voidIds.length > 0 ? reason.trim() : "",
            })
          }
        >
          Spara korrigering
        </button>
      </DialogActions>
    </Dialog>
  );
}
