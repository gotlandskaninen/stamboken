"use client";

import React from "react";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import {
  fmtDate,
  fmtTime,
  refusalText,
  type Receipt as ReceiptData,
  type ReportView,
  type Summary,
} from "./lib";
import { ReportStatus } from "./ReportStatus";
import styles from "./arsrapport.module.css";

const WITHDRAW_TEXT =
  "Rapporten dras tillbaka. Kaninerna räknas inte som levande 31 december förrän du skickar igen. Försäljningar som väntar tas bort. Det du fyllt i finns kvar.";

function summaryOf(view: ReportView): Summary {
  const s: Summary = { kvar: 0, doda: 0, salda: 0, ej_angivna: 0 };
  for (const e of Object.values(view.report?.submitted?.rabbits ?? {})) {
    if (e.val === "kvar") s.kvar++;
    else if (e.val === "dod") s.doda++;
    else if (e.val === "sald") s.salda++;
    else if (e.val === "ej_angiven") s.ej_angivna++;
  }
  return s;
}

export function Receipt({
  view,
  receipt,
  hasDraft,
  busy,
  onChange,
  onWithdraw,
}: {
  view: ReportView;
  receipt: ReceiptData | null;
  hasDraft: boolean;
  busy: boolean;
  onChange: () => void;
  onWithdraw: (reason?: string) => Promise<string | null>;
}) {
  const report = view.report; // null until the refreshed view arrives after the first Skicka
  const editor = view.access === "manager" || view.access === "admin";
  const [asking, setAsking] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [error, setError] = React.useState<string | null>(null);
  const sum = receipt?.summary ?? summaryOf(view);
  const hasSale = Object.values(report?.submitted?.rabbits ?? {}).some(
    (e) => e.val === "sald",
  );
  // A caretaker cannot back out a sale (D12), so the button is not offered.
  const canWithdraw =
    !!report?.can_withdraw && !(view.access === "caretaker" && hasSale);
  const at = report?.received_at ?? receipt?.created_at ?? "";
  const when = `${fmtDate(at)} kl. ${fmtTime(at)}`;
  const changed =
    report &&
    report.report_date.slice(0, 10) !== report.received_at.slice(0, 10)
      ? ` · ändrad ${fmtDate(report.report_date)}`
      : "";
  const v = report?.villkor;
  const mark = (ok: boolean, label: string) => (
    <span key={label} className={ok ? styles.yes : styles.no}>
      {ok ? "✓" : "✗"} {label}
    </span>
  );

  const withdraw = async () => {
    setError(null);
    const e = await onWithdraw(editor ? reason.trim() : undefined);
    if (e) setError(e);
    else setAsking(false);
  };

  return (
    <>
      <ReportStatus
        status={{ kind: "submitted", text: `Inskickad${changed}` }}
      />
      <h2 className={styles.headline}>
        Klart. Årsrapporten för {view.herd.herd} kom in {when}.
      </h2>
      <div className={styles.stats}>
        {[
          ["Finns kvar", sum.kvar],
          ["Döda", sum.doda],
          ["Sålda", sum.salda],
          ...(sum.ej_angivna ? [["Ej angivna", sum.ej_angivna]] : []),
        ].map(([label, n]) => (
          <div key={label}>
            <div className={styles.statNum}>{n}</div>
            <div className={styles.statLabel}>{label}</div>
          </div>
        ))}
      </div>
      {v && (
        <p className={styles.line}>
          {mark(v.hane, "Hane")} {mark(v.hona, "Hona")} {mark(v.kull, "Kull")}{" "}
          {mark(v.i_tid, "I tid")}
        </p>
      )}
      {receipt && receipt.warnings.length > 0 && (
        <div className={`${styles.status} ${styles.warning}`}>
          {receipt.warnings.map((w, i) => {
            const r = view.rabbits.find((x) => x.id === w.individual_id);
            return (
              <p key={i}>
                {r ? `${r.number} ${r.name ?? ""}`.trim() + ": " : ""}
                {refusalText(w)}
              </p>
            );
          })}
        </div>
      )}
      {hasDraft && (
        <ReportStatus status={{ kind: "saved", at: null, changing: true }}>
          <p>Du har ändringar som inte är inskickade.</p>
        </ReportStatus>
      )}
      {!report ? null : report.can_change ? (
        <div className={styles.actions}>
          <button
            type="button"
            className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
            onClick={onChange}
            disabled={busy}
          >
            {hasDraft ? "Fortsätt ändra" : "Ändra"}
          </button>
          <span
            className={styles.meta}
            style={{ alignSelf: "center", margin: 0 }}
          >
            {view.round.end_date
              ? `till och med ${fmtDate(view.round.end_date)}`
              : ""}
          </span>
        </div>
      ) : (
        <ReportStatus status={{ kind: "closed" }} />
      )}
      {canWithdraw && (
        <div className={styles.actions}>
          <button
            type="button"
            className={`sb-btn sb-btn-ghost ${styles.btn} ${styles.danger}`}
            onClick={() => setAsking(true)}
            disabled={busy}
          >
            Dra tillbaka
          </button>
          <span
            className={styles.meta}
            style={{ alignSelf: "center", margin: 0 }}
          >
            {report?.withdraw_until
              ? `till och med ${fmtDate(report?.withdraw_until)}`
              : ""}
          </span>
        </div>
      )}
      <Dialog
        open={asking}
        onClose={() => setAsking(false)}
        aria-labelledby="wd-title"
      >
        <DialogTitle id="wd-title">Dra tillbaka rapporten</DialogTitle>
        <DialogContent className={styles.detail}>
          <p style={{ margin: 0 }}>{WITHDRAW_TEXT}</p>
          {editor && (
            <label className={styles.label}>
              Varför dras rapporten tillbaka?
              <textarea
                className={styles.field}
                rows={2}
                maxLength={500}
                value={reason}
                onChange={(e) => setReason(e.target.value)}
              />
            </label>
          )}
          {error && (
            <p className={styles.errorText} role="alert">
              {error}
            </p>
          )}
        </DialogContent>
        <DialogActions>
          <button
            type="button"
            className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
            onClick={() => setAsking(false)}
          >
            Avbryt
          </button>
          <button
            type="button"
            className={`sb-btn ${styles.btn}`}
            disabled={busy || (editor && !reason.trim())}
            onClick={withdraw}
          >
            Dra tillbaka rapporten
          </button>
        </DialogActions>
      </Dialog>
    </>
  );
}
