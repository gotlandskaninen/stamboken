"use client";

import { useEffect, useMemo, useRef, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Mode } from "@/lib/mode";
import { useMode } from "@/lib/mode-context";
import { ConfirmDialog } from "../../../admin/_components/ConfirmDialog";
import {
  newLink,
  sendReminder,
  setOnTime,
  undoAccountLink,
} from "../../actions";
import {
  INVITATION_TEXT,
  ROW_STATES,
  ROW_STATE_FILTER,
  ROW_STATE_TEXT,
  countByState,
  filterRows,
  fmtDate,
  phoneNumbers,
  todayStockholm,
  wordForm,
  type RowState,
  type StatusFilter,
  type StatusRow,
  type StatusView,
} from "../../lib";
import styles from "../../arsrapport.module.css";
import inkorg from "../../../inkorg/inkorg.module.css";
import { SalesDialog } from "./SalesDialog";

const SOURCE_TEXT = { paper: "blankett", login: "inloggad", link: "länk" };
const MEMBERSHIP_TEXT = {
  kvar_utan_genbank: "Medlemskapet består",
  avsluta_medlemskap: "Medlemskapet avslutas",
};
const BADGE: Partial<Record<RowState, string>> = {
  ingen_epost: inkorg.badgeWarn,
  blankett_vantar: inkorg.badgeWarn,
  blankett_inkommen: styles.badgeInfo,
  inskickad: styles.badgeDone,
};
const CONDITIONS = [
  ["hane", "Hane"],
  ["hona", "Hona"],
  ["kull", "Kull"],
  ["i_tid", "I tid"],
] as const;
const ON_TIME = { "": null, ja: true, nej: false } as const;

function reminderText(reminder: StatusRow["last_reminder"]) {
  switch (reminder?.status) {
    case "queued":
    case "sending":
      return "Påminnelse i mejlkön";
    case "sent":
      return reminder.sent_at
        ? `Påminnelse skickad ${fmtDate(reminder.sent_at)}`
        : null;
    case "failed":
      return "Påminnelsen misslyckades";
    case "bounced":
      return "Påminnelsen studsade";
    default:
      return null;
  }
}

// "Skriv ut tom blankett": the blank form is generic, so the page has one link.
export function BlankFormLink({ available }: { available: boolean }) {
  const mode = useMode();
  const apiBase =
    mode === "demo" && process.env.NEXT_PUBLIC_API_TEST_URL
      ? process.env.NEXT_PUBLIC_API_TEST_URL
      : "/api";
  if (!available)
    return (
      <p className={`${inkorg.muted} ${styles.blankMissing}`}>
        Den tomma blanketten finns inte på servern än.
      </p>
    );
  return (
    <a
      href={`${apiBase}/v2/arsrapport/blankett.pdf`}
      target="_blank"
      rel="noopener noreferrer"
      className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
    >
      Skriv ut tom blankett
    </a>
  );
}

export function StatusTable({
  view,
  year,
  genebankId,
  filter,
  canEdit,
  env,
}: {
  view: StatusView;
  year: number;
  genebankId: number;
  filter: StatusFilter;
  canEdit: boolean;
  env: Mode;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [busy, setBusy] = useState(false);
  const [ask, setAsk] = useState<string | null>(null); // the herd whose "Ny länk" awaits its confirmation
  const [sales, setSales] = useState<string | null>(null); // the herd whose "Försäljningar" is open
  // the herd and account link whose "Koppla bort" awaits its yes
  const [unlink, setUnlink] = useState<{ herd: string; id: number } | null>(
    null,
  );
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const deadline = view.round.deadline;
  // Today in Stockholm is read once per render of the filtered list.
  const today = todayStockholm();
  const counts = useMemo(() => countByState(view.rows), [view.rows]);
  const callCount = filterRows(view.rows, "att_ringa", deadline, today).length;
  const unanswered = filterRows(view.rows, "ej_svarat", deadline, today).length;
  const rows = filterRows(view.rows, filter, deadline, today);

  const href = (f: StatusFilter) => {
    const q = new URLSearchParams({ genebank_id: String(genebankId) });
    if (f !== "alla") q.set("filter", f);
    return `/stamboken/arsrapport/status/${year}?${q}`;
  };
  const tabs: [StatusFilter, string, number | null][] = [
    ["att_ringa", "Att ringa", callCount],
    ["ej_svarat", "Ej svarat", unanswered],
    ...ROW_STATES.filter((s) => counts[s] > 0 || s === filter).map(
      (s): [StatusFilter, string, number] => [
        s,
        ROW_STATE_FILTER[s],
        counts[s],
      ],
    ),
    ["alla", "Alla", view.rows.length],
  ];

  async function changeOnTime(herd: string, value: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await setOnTime(
        herd,
        year,
        ON_TIME[value as keyof typeof ON_TIME] ?? null,
        env,
      );
      if (!res.ok) setError(res.problem.detail || res.problem.title);
      else startTransition(() => router.refresh());
    } catch {
      setError("Det gick inte att nå servern. Försök igen.");
    } finally {
      setBusy(false);
    }
  }

  async function sendLink(herd: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await newLink(herd, year, env);
      if (!res.ok) setError(res.problem.detail || res.problem.title);
      else startTransition(() => router.refresh());
    } catch {
      setError("Det gick inte att nå servern. Försök igen.");
    } finally {
      setBusy(false);
      setAsk(null);
    }
  }

  async function remind(herd: string) {
    if (busy) return;
    setBusy(true);
    setError(null);
    setMessage(null);
    try {
      const res = await sendReminder(herd, year, env);
      if (!res.ok) setError(res.problem.detail || res.problem.title);
      else {
        setMessage(
          res.data.queued
            ? "Påminnelsen ligger i mejlkön."
            : "En påminnelse finns redan i mejlkön eller har skickats i dag.",
        );
        startTransition(() => router.refresh());
      }
    } catch {
      setError("Det gick inte att nå servern. Försök igen.");
    } finally {
      setBusy(false);
    }
  }

  async function undoLink(link: { herd: string; id: number }) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      const res = await undoAccountLink(link.herd, year, link.id, env);
      if (!res.ok) setError(res.problem.detail || res.problem.title);
      else startTransition(() => router.refresh());
    } catch {
      setError("Det gick inte att nå servern. Försök igen.");
    } finally {
      setBusy(false);
      setUnlink(null);
    }
  }

  return (
    <>
      <ConfirmDialog
        open={unlink !== null}
        title="Koppla bort kontot"
        body="Koppla bort kontot från medlemskapet? Åtkomsten som medlemskapskopplingen gav försvinner för medlemskapets besättningar. Andra behörigheter påverkas inte."
        confirmLabel="Koppla bort"
        busy={busy}
        onConfirm={() => unlink !== null && undoLink(unlink)}
        onClose={() => setUnlink(null)}
      />
      <ConfirmDialog
        open={ask !== null}
        title={`Ny länk till ${ask ?? ""}`}
        body="Den gamla länken slutar gälla. Skicka en ny länk till huvudmedlemmen?"
        confirmLabel="Skicka ny länk"
        busy={busy}
        onConfirm={() => ask && sendLink(ask)}
        onClose={() => setAsk(null)}
      />
      {sales && (
        <SalesDialog
          herd={sales}
          year={year}
          env={env}
          onDecided={() => startTransition(() => router.refresh())}
          onClose={() => setSales(null)}
        />
      )}
      <nav className={inkorg.counts} aria-label="Lägen">
        {tabs.map(([f, label, n]) => (
          <Link
            key={f}
            href={href(f)}
            className={`${inkorg.count} ${
              f === "att_ringa" && n ? styles.callTone : ""
            }`}
            aria-current={filter === f ? "page" : undefined}
          >
            {label}
            {n !== null && <strong>{n}</strong>}
          </Link>
        ))}
      </nav>
      {error && (
        <p
          ref={errorRef}
          tabIndex={-1}
          role="alert"
          className={styles.tableError}
        >
          {error}
        </p>
      )}
      {message && (
        <p role="status" className={inkorg.muted}>
          {message}
        </p>
      )}
      {rows.length === 0 ? (
        <p className={inkorg.muted}>
          {filter === "alla"
            ? "Inga besättningar i genbanken."
            : filter === "att_ringa"
              ? "Inga besättningar att ringa."
              : filter === "ej_svarat"
                ? "Alla besättningar har svarat."
                : `Inga besättningar i ${ROW_STATE_FILTER[filter]}.`}
        </p>
      ) : (
        <section className="sb-card">
          <table className={`${inkorg.table} ${styles.statusTable}`}>
            <thead>
              <tr>
                <th>Besättning</th>
                <th>Läge</th>
                <th>Villkor för stödet</th>
                <th>Flaggor</th>
                <th>Mottagen</th>
                <th>Åtgärd</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <Row
                  key={row.herd}
                  row={row}
                  year={year}
                  canEdit={canEdit}
                  locked={busy || pending}
                  onTime={changeOnTime}
                  onNewLink={setAsk}
                  onReminder={remind}
                  onSales={setSales}
                  onUnlink={setUnlink}
                />
              ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}

function Row({
  row,
  year,
  canEdit,
  locked,
  onTime,
  onNewLink,
  onReminder,
  onSales,
  onUnlink,
}: {
  row: StatusRow;
  year: number;
  canEdit: boolean;
  locked: boolean;
  onTime: (herd: string, value: string) => void;
  onNewLink: (herd: string) => void;
  onReminder: (herd: string) => void;
  onSales: (herd: string) => void;
  onUnlink: (link: { herd: string; id: number }) => void;
}) {
  const reported = row.received_at !== null;
  const reminder = reminderText(row.last_reminder);
  // The state already says "Ingen e-post" when nothing else is going on.
  const flagNoEmail = row.ingen_epost && row.state !== "ingen_epost";
  const override =
    row.on_time_override === null ? "" : row.on_time_override ? "ja" : "nej";
  const f = row.flags;
  const flagged =
    flagNoEmail ||
    f.ej_angivna > 0 ||
    f.forsaljning_vantar > 0 ||
    f.forsaljning_avvisad > 0 ||
    f.kopt_efter_inskick > 0 ||
    f.kop_anmalt > 0 ||
    !!f.andring_vantar ||
    !!f.kontobyte_vantar ||
    !!f.kontobyte_forfoll ||
    !!f.inte_jag ||
    !!f.nytt_konto ||
    row.statistik.preliminart;
  return (
    <tr>
      <td>
        <Link
          href={`/stamboken/arsrapport/${row.herd}/${year}`}
          className={styles.herdLink}
        >
          {row.herd}
        </Link>
        {row.herd_name && row.herd_name !== "-" && (
          <div className={inkorg.muted}>{row.herd_name}</div>
        )}
        {row.telefon &&
          phoneNumbers(row.telefon).map((phone, i) => (
            <div key={i}>
              <a
                className={styles.phone}
                href={`tel:${phone.replace(/[^\d+]/g, "")}`}
              >
                {phone}
              </a>
            </div>
          ))}
      </td>
      <td data-label="Läge">
        <span className={`sb-badge ${BADGE[row.state] ?? ""}`}>
          {ROW_STATE_TEXT[row.state]}
        </span>
        {row.source && (
          <span className={inkorg.muted}> {SOURCE_TEXT[row.source]}</span>
        )}
        {row.inbjudan && (
          <div className={inkorg.muted}>{INVITATION_TEXT[row.inbjudan]}</div>
        )}
        {reminder && <div className={inkorg.muted}>{reminder}</div>}
        {row.state === "avslutar" && row.membership_after_end && (
          <div className={inkorg.muted}>
            {MEMBERSHIP_TEXT[row.membership_after_end]}
          </div>
        )}
      </td>
      <td data-label="Villkor för stödet">
        {reported
          ? CONDITIONS.map(([key, label]) => (
              <span key={key} className={styles.condition}>
                {label}{" "}
                {row.villkor[key] ? (
                  <span className={styles.yes}>✓</span>
                ) : (
                  <span className={styles.no}>✗</span>
                )}
              </span>
            ))
          : "–"}
      </td>
      <td data-label="Flaggor">
        {flagged ? (
          <div className={styles.flags}>
            {flagNoEmail && <span className="sb-badge">Ingen e-post</span>}
            {row.statistik.preliminart && (
              <span className="sb-badge">Preliminärt antal</span>
            )}
            {f.ej_angivna > 0 && (
              <span
                className={`sb-badge ${f.ej_angivna_paverkar ? inkorg.badgeWarn : ""}`}
              >
                {f.ej_angivna} ej {wordForm(f.ej_angivna, "angiven", "angivna")}
                {f.ej_angivna_paverkar && " (påverkar stödet)"}
              </span>
            )}
            {f.forsaljning_vantar > 0 && (
              <span className="sb-badge">
                {f.forsaljning_vantar === 1
                  ? "Försäljning väntar"
                  : `${f.forsaljning_vantar} försäljningar väntar`}
              </span>
            )}
            {f.forsaljning_avvisad > 0 && (
              <span
                className={`sb-badge ${
                  f.forsaljning_avvisad_paverkar ? inkorg.badgeWarn : ""
                }`}
              >
                Försäljning avvisad, medlemmen väljer igen
                {f.forsaljning_avvisad_paverkar && " (påverkar stödet)"}
              </span>
            )}
            {f.kopt_efter_inskick > 0 && (
              <span className="sb-badge">Köpt efter inskick</span>
            )}
            {f.kop_anmalt > 0 && (
              // purchase notices with no pending sale: registered from the queue (4a Task 5)
              <Link
                href={`/stamboken/inkorg?herd=${row.herd}&kind=kontroll`}
                className="sb-badge"
              >
                {f.kop_anmalt === 1
                  ? "Köp anmält"
                  : `${f.kop_anmalt} köp anmälda`}
              </Link>
            )}
            {!!f.andring_vantar && (
              <span className="sb-badge">Ändring väntar på bekräftelse</span>
            )}
            {f.kontobyte_vantar && (
              <span className={`sb-badge ${inkorg.badgeWarn}`}>
                Kontobyte väntar på bekräftelse
              </span>
            )}
            {f.kontobyte_forfoll && (
              <span className={`sb-badge ${inkorg.badgeWarn}`}>
                Kontobyte förföll
              </span>
            )}
            {f.inte_jag && (
              <span className={`sb-badge ${inkorg.badgeWarn}`}>
                Det var inte jag
              </span>
            )}
            {!!f.nytt_konto && <span className="sb-badge">Nytt konto</span>}
          </div>
        ) : (
          "–"
        )}
      </td>
      <td data-label="Mottagen">
        {row.received_at ? fmtDate(row.received_at) : "–"}
      </td>
      <td>
        <div className={inkorg.rowActions}>
          {row.state !== "inskickad" && (
            <Link
              href={`/stamboken/inkorg?herd=${row.herd}`}
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
            >
              Mata in blankett
            </Link>
          )}
          {canEdit && !row.ingen_epost && (
            <button
              type="button"
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
              disabled={locked}
              onClick={() => onNewLink(row.herd)}
            >
              Ny länk
            </button>
          )}
          {canEdit && row.needs_report && !row.ingen_epost && (
            <button
              type="button"
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
              disabled={locked}
              onClick={() => onReminder(row.herd)}
            >
              Skicka påminnelse
            </button>
          )}
          {canEdit && !!row.flags.nytt_konto && (
            <button
              type="button"
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
              disabled={locked}
              onClick={() =>
                onUnlink({ herd: row.herd, id: row.flags.nytt_konto! })
              }
            >
              Koppla bort kontot
            </button>
          )}
          {canEdit && row.flags.forsaljning_vantar > 0 && (
            <button
              type="button"
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
              disabled={locked}
              onClick={() => onSales(row.herd)}
            >
              Försäljningar
            </button>
          )}
          {canEdit && reported && (
            <label>
              I tid{" "}
              <select
                className={`sb-input ${styles.field}`}
                value={override}
                disabled={locked}
                onChange={(e) => onTime(row.herd, e.target.value)}
              >
                <option value="">Räknas</option>
                <option value="ja">Ja</option>
                <option value="nej">Nej</option>
              </select>
            </label>
          )}
        </div>
      </td>
    </tr>
  );
}
