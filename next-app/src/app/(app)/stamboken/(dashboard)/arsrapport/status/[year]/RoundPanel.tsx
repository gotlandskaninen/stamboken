"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Mode } from "@/lib/mode";
import { activateGenebank, saveRound, sendTestMail } from "../../actions";
import { defaultRoundDates, fmtDate, type Round } from "../../lib";
import styles from "../../arsrapport.module.css";
import inkorg from "../../../inkorg/inkorg.module.css";

const DATES = [
  ["start_date", "Öppnar"],
  ["deadline", "Sista dag för stödet"],
  ["end_date", "Stänger"],
] as const;

export function RoundPanel({
  year,
  genebankId,
  genebankName,
  round,
  closed = false,
  canEdit,
  recipients,
  env,
}: {
  year: number;
  genebankId: number;
  genebankName: string;
  round: Round | null;
  closed?: boolean;
  canEdit: boolean;
  recipients: { med_epost: number; utan_epost: number } | null;
  env: Mode;
}) {
  const router = useRouter();
  const activation = round?.genebanks.find((g) => g.genebank_id === genebankId);
  // A date the round lacks shows the default the server would give it.
  const defaults = defaultRoundDates(year);
  const [dates, setDates] = useState({
    start_date: round?.start_date ?? defaults.start_date,
    deadline: round?.deadline ?? defaults.deadline,
    end_date: round?.end_date ?? defaults.end_date,
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [testSent, setTestSent] = useState(false);
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const changedKeys = DATES.filter(
    ([key]) => dates[key] !== "" && dates[key] !== (round?.[key] ?? ""),
  ).map(([key]) => key);
  // Dates the server has not filled in yet get its defaults before activation.
  const incomplete = round === null || DATES.some(([key]) => !round[key]);

  async function run(activate: boolean) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      // Only what the user changed is sent; empty dates are left to the server's defaults.
      const body = Object.fromEntries(
        changedKeys.map((key) => [key, dates[key]]),
      );
      if (changedKeys.length > 0 || (activate && incomplete)) {
        const saved = await saveRound(year, body, env);
        if (!saved.ok) {
          setError(saved.problem.detail || saved.problem.title);
          return;
        }
      }
      if (activate) {
        const done = await activateGenebank(year, genebankId, env);
        if (!done.ok) {
          setError(done.problem.detail || done.problem.title);
          return;
        }
      }
      router.refresh();
    } catch {
      setError("Det gick inte att nå servern. Försök igen.");
    } finally {
      setBusy(false);
    }
  }

  async function testMail() {
    if (busy) return;
    setBusy(true);
    setError(null);
    setTestSent(false);
    try {
      const done = await sendTestMail(year, genebankId, env);
      if (done.ok) setTestSent(true);
      else setError(done.problem.detail || done.problem.title);
    } catch {
      setError("Det gick inte att nå servern. Försök igen.");
    } finally {
      setBusy(false);
    }
  }

  // The count of the invitation's recipients and the test mail, once the round exists.
  const invitation = recipients && (
    <>
      <p style={{ margin: 0 }}>
        Inbjudan går till {recipients.med_epost}{" "}
        {recipients.med_epost === 1 ? "besättning" : "besättningar"}.{" "}
        {recipients.utan_epost} saknar e-post och får blanketten med post.
      </p>
      {canEdit && (
        <div className={styles.actions}>
          <button
            type="button"
            className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
            disabled={busy}
            onClick={testMail}
          >
            Skicka provmejl till mig
          </button>
        </div>
      )}
      {testSent && (
        <p role="status" className={inkorg.muted}>
          Provmejlet är på väg till din e-postadress.
        </p>
      )}
    </>
  );

  const form = (
    <div className={styles.dates}>
      {DATES.map(([key, label]) => (
        <label key={key}>
          {label}
          <input
            type="date"
            className={`sb-input ${styles.field}`}
            value={dates[key]}
            disabled={busy || !canEdit}
            onChange={(e) => setDates({ ...dates, [key]: e.target.value })}
          />
        </label>
      ))}
    </div>
  );
  const problem = error && (
    <p ref={errorRef} tabIndex={-1} role="alert" className={styles.tableError}>
      {error}
    </p>
  );

  if (closed && round?.end_date)
    return (
      <section className={`sb-card ${styles.roundCard}`}>
        <h2>Rundan {year} är stängd</h2>
        <p className={inkorg.muted} style={{ margin: 0 }}>
          Den stängde {fmtDate(round.end_date)} utan att ha aktiverats för{" "}
          {genebankName}. Rapporter som skickades i gamla Stamboken visas inte
          här.
        </p>
      </section>
    );

  if (!activation)
    return (
      <section className={`sb-card ${styles.roundCard}`}>
        <h2>
          {round === null
            ? `Rundan ${year} finns inte än`
            : `Rundan ${year} är inte aktiverad för ${genebankName}`}
        </h2>
        {canEdit ? (
          <>
            {form}
            <p className={inkorg.muted}>Datumen gäller alla genbanker.</p>
            {invitation}
            <div className={styles.actions}>
              <button
                type="button"
                className={`sb-btn ${styles.btn}`}
                disabled={busy}
                onClick={() => run(true)}
              >
                {busy ? "Sparar …" : "Aktivera"}
              </button>
            </div>
          </>
        ) : (
          <>
            <p className={inkorg.muted}>Genbanksansvarig aktiverar rundan.</p>
            {invitation}
          </>
        )}
        {problem}
      </section>
    );

  return (
    <section className={`sb-card ${styles.roundCard}`}>
      <p style={{ margin: 0 }}>
        Aktiverad {fmtDate(activation.activated_at)} av{" "}
        {activation.activated_by.name}
        {round?.start_date && ` · öppnar ${fmtDate(round.start_date)}`}
        {round?.deadline &&
          ` · sista dag för stödet ${fmtDate(round.deadline)}`}
        {round?.end_date && ` · stänger ${fmtDate(round.end_date)}`}
        {activation.sent_at
          ? `. Inbjudningarna skickades ${fmtDate(activation.sent_at)}`
          : activation.send_at &&
            `. Inbjudningarna skickas ${fmtDate(activation.send_at)} kl. 07`}
      </p>
      {!activation.sent_at && invitation}
      {canEdit && (
        <details>
          <summary>Ändra datum</summary>
          {form}
          <p className={inkorg.muted}>Datumen gäller alla genbanker.</p>
          <div className={styles.actions}>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              disabled={busy || changedKeys.length === 0}
              onClick={() => run(false)}
            >
              {busy ? "Sparar …" : "Spara datum"}
            </button>
          </div>
        </details>
      )}
      {problem}
    </section>
  );
}
