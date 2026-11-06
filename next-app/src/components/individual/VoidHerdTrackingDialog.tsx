"use client";

import React from "react";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import {
  KIND_LABELS,
  isBeforeLatestSnapshot,
  newOperationId,
  type HerdTrackingRow,
} from "@/lib/herdTracking";
import styles from "./VoidHerdTrackingDialog.module.css";

export type VoidMode = "void" | "undoSale" | "undoOperation";

export const BUYER_PRIVACY_HELP =
  "Skriv inte köparens namn eller kontaktuppgifter.";
export const GENETICS_INFO =
  "Historisk genetikstatistik räknas inte om när en äldre händelse ångras.";

// The server rejects e-mail/phone with the help text; do not repeat it verbatim.
const PRIVACY_REJECTED =
  "Texten innehåller en e-postadress eller ett telefonnummer. Ta bort den och försök igen.";

/** Inline text for a herd-tracking server error (shared by the void and correction dialogs). */
export function htErrorMessage(error: string): string {
  return error === BUYER_PRIVACY_HELP ? PRIVACY_REJECTED : error;
}

const TITLES: Record<VoidMode, string> = {
  void: "Ångra",
  undoSale: "Ångra försäljning",
  undoOperation: "Ångra hela åtgärden",
};

interface VoidHerdTrackingDialogProps {
  open: boolean;
  row: HerdTrackingRow | null;
  mode: VoidMode;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onConfirm: (reason: string, operationId: string) => void;
}

/**
 * Remounted per opening: the reason and the operation id never survive a close.
 * (Same wrapper as HerdTrackingCorrectionDialog — duplicated on purpose, a hook is not worth it.)
 */
export function VoidHerdTrackingDialog(props: VoidHerdTrackingDialogProps) {
  const [openings, setOpenings] = React.useState(0);
  const [wasOpen, setWasOpen] = React.useState(props.open);
  if (props.open !== wasOpen) {
    setWasOpen(props.open);
    if (props.open) setOpenings((n) => n + 1);
  }
  // MUI keeps the dialog mounted for its exit animation, but the parent clears
  // row/mode on close: keep the last target so the title does not flip.
  const [last, setLast] = React.useState({ row: props.row, mode: props.mode });
  if (props.row && (props.row !== last.row || props.mode !== last.mode)) {
    setLast({ row: props.row, mode: props.mode });
  }
  const row = props.row ?? last.row;
  const mode = props.row ? props.mode : last.mode;
  return <VoidDialogContent key={openings} {...props} row={row} mode={mode} />;
}

function VoidDialogContent({
  open,
  row,
  mode,
  busy,
  error,
  onClose,
  onConfirm,
}: VoidHerdTrackingDialogProps) {
  const [reason, setReason] = React.useState("");
  // One operation per dialog opening: retries and double clicks are idempotent.
  const [operationId] = React.useState(newOperationId);
  const trimmed = reason.trim();
  return (
    <Dialog
      open={open}
      onClose={busy ? undefined : onClose}
      fullWidth
      maxWidth="sm"
    >
      <DialogTitle>{TITLES[mode]}</DialogTitle>
      <DialogContent>
        {row && (
          <p className="sb-meta">
            {row.date} · {KIND_LABELS[row.kind]} · {row.herd.label}
          </p>
        )}
        <label className="sb-label" htmlFor="ht-void-reason">
          Anledning
        </label>
        <textarea
          id="ht-void-reason"
          className="sb-input"
          rows={3}
          value={reason}
          aria-describedby="ht-void-help"
          onChange={(e) => setReason(e.target.value)}
        />
        <p id="ht-void-help" className="sb-meta">
          {BUYER_PRIVACY_HELP}
        </p>
        {row && isBeforeLatestSnapshot(row.date) && (
          <p className="sb-meta" role="note">
            {GENETICS_INFO}
          </p>
        )}
        {error && (
          <p
            role="alert"
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
          disabled={busy || !trimmed}
          onClick={() => onConfirm(trimmed, operationId)}
        >
          {TITLES[mode]}
        </button>
      </DialogActions>
    </Dialog>
  );
}
