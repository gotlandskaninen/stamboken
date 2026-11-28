"use client";

import React from "react";
import Link from "next/link";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import {
  MATRIKEL_LABEL,
  PENDING_SALE_TEXT,
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
  // the year's sales the report did not write (the sale dialog's, or Sälj), as the receipt counts them
  s.salda += view.report?.submitted?.salda_direkt?.length ?? 0;
  return s;
}

export function Receipt({
  view,
  receipt,
  receivedOn,
  hasDraft,
  busy,
  onChange,
  onWithdraw,
  focusOnMount = false,
  refreshed = false,
  accountOffer = false,
}: {
  view: ReportView;
  receipt: ReceiptData | null;
  receivedOn?: string;
  hasDraft: boolean;
  busy: boolean;
  onChange: () => void;
  onWithdraw: (reason?: string) => Promise<React.ReactNode>;
  focusOnMount?: boolean; // right after a Skicka: show the receipt and read it out
  // the view has been fetched again since the receipt came: it alone says what waits
  refreshed?: boolean;
  // the personal link where code login is on (5.1, fråga 9): offer an account, last
  accountOffer?: boolean;
}) {
  const report = view.report; // null until the refreshed view arrives after the first Skicka
  const editor = view.access === "manager" || view.access === "admin";
  const [asking, setAsking] = React.useState(false);
  const [reason, setReason] = React.useState("");
  const [error, setError] = React.useState<React.ReactNode>(null);
  const headRef = React.useRef<HTMLHeadingElement>(null);
  React.useEffect(() => {
    if (!focusOnMount) return;
    window.scrollTo({ top: 0 });
    headRef.current?.focus();
  }, [focusOnMount]);
  const sum = receipt?.summary ?? summaryOf(view);
  // A caretaker's or the link's withdrawal leaves the owner's sales standing (FB5), so it is always offered.
  const canWithdraw = !!report?.can_withdraw;
  // right after Skicka, until the view is fetched again, the receipt says what waits; then the view alone, since a
  // retry's receipt is the first one and a proposal may have been decided meanwhile
  const pendingSale =
    receipt && !refreshed
      ? !!receipt.summary.vantar
      : view.forslag.some((p) => p.state === "foreslagen");
  const at = report?.received_at ?? receipt?.created_at ?? "";
  const source = receipt && !refreshed ? receipt.source : report?.source;
  const when =
    source === "paper" || report?.from_paper
      ? fmtDate(receivedOn ?? report?.submitted?.received_on ?? at)
      : `${fmtDate(at)} kl. ${fmtTime(at)}`;
  const changed =
    report &&
    report.report_date.slice(0, 10) !== report.received_at.slice(0, 10)
      ? ` · ändrad ${fmtDate(report.report_date)}`
      : "";
  const v = report?.villkor;
  // 5.11: the link's changes that wait for the receipt mail, and those that expired
  const details = view.member_details;
  const changes = details?.mode === "link" ? details.changes : [];
  const waiting = changes.filter((c) => c.state === "vantar");
  const expired = changes.filter((c) => c.state === "forfallen");
  const labels = (list: typeof changes) =>
    [...new Set(list.map((c) => MATRIKEL_LABEL[c.falt] ?? c.falt))].join(", ");
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
      <h2 ref={headRef} tabIndex={-1} className={styles.headline}>
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
      {pendingSale && <p className={styles.meta}>{PENDING_SALE_TEXT}</p>}
      {receipt && receipt.source !== "paper" && receipt.matrikel.length > 0 && (
        <p className={styles.meta}>
          Sparat i matrikeln:{" "}
          {receipt.matrikel.map((f) => MATRIKEL_LABEL[f] ?? f).join(", ")}.
        </p>
      )}
      {waiting.length > 0 && (
        <p className={styles.meta}>
          Du har ändringar att bekräfta i mejlet ({labels(waiting)}). Bekräfta
          senast {fmtDate(waiting.map((c) => c.expires_at).sort()[0])}.
        </p>
      )}
      {expired.length > 0 && (
        <p className={styles.meta}>
          Ändringen av {labels(expired)} gällde till{" "}
          {fmtDate(expired.map((c) => c.expires_at).sort()[0])}. Vill du ändå
          ändra? Tryck Ändra och fyll i den igen.
        </p>
      )}
      {v && (
        <p className={styles.line}>
          Villkor för stödet: {mark(v.hane, "Hane")} {mark(v.hona, "Hona")}{" "}
          {mark(v.kull, "Kull")} {mark(v.i_tid, "I tid")}
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
      {accountOffer && (
        <div className={styles.detail}>
          <p style={{ margin: 0 }}>
            Gör det löpande nästa år: skapa ett konto i Stamboken. Du loggar in
            med en kod som vi mejlar till din e-postadress hos föreningen.
          </p>
          <Link
            href="/auth/sign-in"
            className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
          >
            Skapa konto
          </Link>
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
          <p style={{ margin: 0 }}>
            Vill du bara rätta något? Använd Ändra i stället.
          </p>
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
            className={`sb-btn ${styles.btn} ${styles.confirmDanger}`}
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
