"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { CoatChoice } from "@/components/herd/CoatChoice";
import {
  ProposalChecks,
  RegisterFromCertificate,
  type Lookup,
} from "@/components/register/RegisterFromCertificate";
import { reconcileDocument, saveCertificate } from "../actions";
import {
  initialCertForm,
  initialGrandparents,
  initialSaveMode,
  normalNumber,
  shownProposal,
  type CertForm,
  type Grandparents,
  type InboxDocument,
  type Proposal,
  type Reconciliation,
  type RowKey,
  type SaveMode,
} from "../lib";
import { missingRows, ReconcileTable } from "./ReconcileTable";
import styles from "../inkorg.module.css";

const RECOMPUTE_MS = 250; // after the last keystroke
// The table looks the registry up through …/avstamning, not number by number.
const noLookup: Lookup = async () => undefined;
// The numbers as the table matched them ("g9001 2411" is G9001-2411), so what stämmer is what Spara sends.
const NUMBERS = ["individual", "paper_number", "mother", "father"];
// Okänt is sent as normal registration sends it: null.
const asMatched = (payload: Record<string, unknown>) =>
  Object.fromEntries(
    Object.entries(payload).map(([key, value]) => [
      key,
      key === "sex" && value === "unknown"
        ? null
        : NUMBERS.includes(key) && typeof value === "string"
          ? (normalNumber(value) ?? value)
          : value,
    ]),
  );

/**
 * What a certificate shows, saved with …/spara: a new rabbit, or the paper
 * certificate on a rabbit that exists. Each row starts empty or with what the
 * image reading read and the registry confirmed, beside the registry in
 * ReconcileTable, with the checks recomputed from what is typed. Nothing is
 * saved until Spara. The saving is RegisterFromCertificate's, shared with the
 * yearly report.
 */
export function CertificateForm({
  itemId,
  doc,
  colors,
  canSave,
  onSaved,
  onSkip,
}: {
  itemId: number;
  doc: InboxDocument;
  colors: string[];
  canSave: boolean;
  onSaved: (document: InboxDocument) => void;
  onSkip: () => void;
}) {
  // The reading may finish while the form is open. What the handler has typed
  // is never replaced: an untouched form takes the reading, a touched one is
  // offered it ("Fyll i det inlästa").
  const latest = shownProposal(doc);
  const [applied, setApplied] = useState(latest !== null);
  const [touched, setTouched] = useState(false);
  const [mode, setModeState] = useState<SaveMode>(() =>
    initialSaveMode(latest),
  );
  const [form, setForm] = useState<CertForm>(() => initialCertForm(latest));
  const [grandparents, setGrandparents] = useState<Grandparents>(() =>
    initialGrandparents(latest),
  );
  const [rex, setRex] = useState(false);
  // Bumped at once on every change: an answer is shown only beside the values it was asked for.
  const [version, setVersion] = useState(0);
  const setMode = (value: SaveMode) => {
    setTouched(true);
    setVersion((v) => v + 1);
    setModeState(value);
  };
  const set = (key: RowKey, value: string) => {
    setTouched(true);
    setVersion((v) => v + 1);
    if (key in grandparents) setGrandparents((g) => ({ ...g, [key]: value }));
    else setForm((f) => ({ ...f, [key]: value }));
  };
  const fill = (p: Proposal) => {
    setVersion((v) => v + 1);
    setForm(initialCertForm(p));
    setGrandparents(initialGrandparents(p));
    setModeState(initialSaveMode(p));
    setApplied(true);
  };
  if (!latest && applied) setApplied(false);
  if (latest && !applied && !touched) fill(latest);

  // The table's rows and checks, recomputed by the API from what is typed.
  // Server Actions run one at a time, so at most one recompute is in flight:
  // changes meanwhile ask once more, for the latest values, and an answer to
  // values since changed is dropped. While Spara saves nothing is asked, so
  // the save never waits behind a recompute it does not need. An answer shows
  // only for the version of the values it was asked for; until the current
  // one has its answer the table waits. A failed recompute, or one the
  // network rejected, shows the error line, and the next change asks again.
  const [answer, setAnswer] = useState<{
    version: number;
    result: Reconciliation;
  } | null>(null);
  const [failed, setFailed] = useState(false);
  const typed = useRef({ version: 0, values: {} as Record<string, string> });
  const inFlight = useRef(false);
  const saving = useRef(false);
  const dirty = useRef(false);
  const ask = useCallback(async () => {
    if (inFlight.current || saving.current) {
      dirty.current = true;
      return;
    }
    inFlight.current = true;
    let sent = typed.current;
    let result: Reconciliation | null = null;
    try {
      do {
        dirty.current = false;
        sent = typed.current;
        try {
          result = await reconcileDocument(itemId, doc.id, sent.values);
        } catch {
          result = null; // the request never reached the API
        }
      } while (dirty.current && !saving.current);
    } finally {
      inFlight.current = false;
    }
    if (dirty.current) return; // asked again once the save is done
    setFailed(result === null);
    if (result) setAnswer({ version: sent.version, result });
  }, [itemId, doc.id]);
  useEffect(() => {
    typed.current = { version, values: { mode, ...form, ...grandparents } };
    const timer = setTimeout(ask, RECOMPUTE_MS);
    return () => clearTimeout(timer);
  }, [version, mode, form, grandparents, latest, ask]);
  const shown = answer?.version === version ? answer.result : null;
  // Spara waits until nothing mandatory is left, as in "Registrera kanin" (Jonas 2026-11-27).
  const lacking = missingRows(mode, { ...form, ...grandparents }, colors);

  return (
    <RegisterFromCertificate
      mode={mode}
      form={form}
      onChange={set}
      rex={rex}
      colors={colors}
      lookup={noLookup}
      canSave={canSave && lacking.length === 0}
      submitLabel="Spara och nästa"
      conflictHint="Stämmer pappret? Lämna ärendet till genbanksansvarig."
      onSave={async (payload) => {
        saving.current = true;
        let res;
        try {
          res = await saveCertificate(itemId, doc.id, asMatched(payload));
        } finally {
          saving.current = false;
        }
        if (res.ok) onSaved(res.data.document);
        else if (dirty.current) void ask();
        return res;
      }}
      header={
        <>
          <h2 className={styles.cardTitle}>Det intyget visar</h2>
          {doc.interpretation_status === "vantar" && (
            <p className={styles.muted}>
              Fotot tolkas. Det inlästa kommer om några minuter; ladda om sidan
              då.
            </p>
          )}
          {doc.interpretation_status === "misslyckad" && (
            <p className={styles.muted}>
              Fotot gick inte att tolka. Skriv av fälten, eller vrid fotot rätt
              och klicka Tolka igen.
            </p>
          )}
          {doc.interpretation_status === "for_litet" && (
            <p className={styles.muted}>
              Fotot är för litet för att tolkas av sig självt.
              {canSave &&
                " Be uppfödaren om ett större foto, skriv av fälten, eller klicka Tolka igen för att tolka det ändå."}
            </p>
          )}
          {latest && !applied && (
            <p className={styles.note}>
              Bildtolkningen har läst fotot.{" "}
              <button
                type="button"
                className="sb-btn sb-btn-secondary sb-btn-sm"
                onClick={() => fill(latest)}
              >
                Fyll i det inlästa
              </button>
            </p>
          )}
          {latest && applied && (
            <p className={styles.note}>
              Jämför varje rad med fotot innan du sparar. Rader där tolkningen
              var osäker eller där pappret avviker från registret är tomma:
              skriv av dem från fotot.
            </p>
          )}
          <div
            className={`${styles.segment}`}
            role="group"
            aria-label="Vad ska sparas"
          >
            {(
              [
                ["ny_kanin", "Ny kanin"],
                ["pappersintyg", "Pappersintyg på en kanin som finns"],
              ] as const
            ).map(([value, label]) => (
              <button
                key={value}
                type="button"
                className="sb-btn sb-btn-secondary sb-btn-sm"
                aria-pressed={mode === value}
                onClick={() => setMode(value)}
              >
                {label}
              </button>
            ))}
          </div>
        </>
      }
      table={(errors) => (
        <>
          <ReconcileTable
            mode={mode}
            values={{ ...form, ...grandparents }}
            onChange={set}
            proposal={latest}
            answer={shown}
            waiting={!shown && !failed}
            colors={colors}
            errors={errors}
          />
          {mode === "ny_kanin" && (
            <CoatChoice
              rex={rex}
              onChange={(value) => {
                setTouched(true);
                setRex(value);
              }}
            />
          )}
        </>
      )}
      afterFields={
        <>
          {failed && (
            <p className={styles.muted} role="status">
              Kontrollerna kunde inte räknas om just nu.
            </p>
          )}
          {shown && <ProposalChecks checks={shown.checks} />}
        </>
      }
      buttons={
        <button
          type="button"
          className="sb-btn sb-btn-secondary"
          onClick={onSkip}
        >
          Hoppa över
        </button>
      }
      footer={
        <>
          {canSave && lacking.length > 0 && (
            <p className={styles.muted} aria-live="polite">
              Kvar att fylla i:{" "}
              {lacking
                .map((label) => label[0].toLowerCase() + label.slice(1))
                .join(", ")}
              .
            </p>
          )}
          <p className={styles.muted}>
            Samma kontroller som när uppfödaren registrerar kaninen.
          </p>
        </>
      }
    />
  );
}
