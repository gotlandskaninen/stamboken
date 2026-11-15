"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import type { Mode } from "@/lib/mode";
import { activateGenebank, saveRound } from "../../actions";
import { fmtDate, type Round } from "../../lib";
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
  canEdit,
  env,
}: {
  year: number;
  genebankId: number;
  genebankName: string;
  round: Round | null;
  canEdit: boolean;
  env: Mode;
}) {
  const router = useRouter();
  const activation = round?.genebanks.find((g) => g.genebank_id === genebankId);
  const [dates, setDates] = useState({
    start_date: round?.start_date ?? "",
    deadline: round?.deadline ?? "",
    end_date: round?.end_date ?? "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const errorRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (error) errorRef.current?.focus();
  }, [error]);

  const changed =
    round === null || DATES.some(([key]) => dates[key] !== (round[key] ?? ""));

  async function run(activate: boolean) {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      // Dates not typed are left to the server's defaults.
      const body = Object.fromEntries(
        DATES.filter(([key]) => dates[key] !== "").map(([key]) => [
          key,
          dates[key],
        ]),
      );
      if (changed) {
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
            <p className={inkorg.muted}>
              Datumen gäller alla genbanker. Inbjudningar skickas när utskicket
              är byggt.
            </p>
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
          <p className={inkorg.muted}>Genbanksansvarig aktiverar rundan.</p>
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
        {!activation.sent_at &&
          ". Inbjudningar skickas när utskicket är byggt."}
      </p>
      {canEdit && (
        <details>
          <summary>Ändra datum</summary>
          {form}
          <p className={inkorg.muted}>Datumen gäller alla genbanker.</p>
          <div className={styles.actions}>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              disabled={busy || !changed}
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
