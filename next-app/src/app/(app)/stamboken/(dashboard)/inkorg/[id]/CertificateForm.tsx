"use client";

import { useEffect, useRef, useState } from "react";
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
  shownProposal,
  type CertForm,
  type Grandparents,
  type InboxDocument,
  type Proposal,
  type Reconciliation,
  type RowKey,
  type SaveMode,
} from "../lib";
import { ReconcileTable } from "./ReconcileTable";
import styles from "../inkorg.module.css";

const RECOMPUTE_MS = 250; // after the last keystroke
// The table looks the registry up through …/avstamning, not number by number.
const noLookup: Lookup = async () => undefined;

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
  const setMode = (value: SaveMode) => {
    setTouched(true);
    setModeState(value);
  };
  const set = (key: RowKey, value: string) => {
    setTouched(true);
    if (key in grandparents) setGrandparents((g) => ({ ...g, [key]: value }));
    else setForm((f) => ({ ...f, [key]: value }));
  };
  const fill = (p: Proposal) => {
    setForm(initialCertForm(p));
    setGrandparents(initialGrandparents(p));
    setModeState(initialSaveMode(p));
    setApplied(true);
  };
  if (!latest && applied) setApplied(false);
  if (latest && !applied && !touched) fill(latest);

  // The table's rows and checks, recomputed by the API from what is typed. An
  // answer to an earlier request than the latest is dropped.
  const [answer, setAnswer] = useState<Reconciliation | null>(null);
  const asked = useRef(0);
  useEffect(() => {
    const request = ++asked.current;
    const timer = setTimeout(async () => {
      const typed = { mode, ...form, ...grandparents };
      const result = await reconcileDocument(itemId, doc.id, typed);
      if (request === asked.current) setAnswer(result);
    }, RECOMPUTE_MS);
    return () => clearTimeout(timer);
  }, [mode, form, grandparents, latest, itemId, doc.id]);

  return (
    <RegisterFromCertificate
      mode={mode}
      form={form}
      onChange={set}
      rex={rex}
      colors={colors}
      lookup={noLookup}
      canSave={canSave}
      submitLabel="Spara och nästa"
      conflictHint="Stämmer pappret? Lämna ärendet till genbanksansvarig."
      onSave={async (payload) => {
        const res = await saveCertificate(itemId, doc.id, payload);
        if (res.ok) onSaved(res.data.document);
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
            answer={answer}
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
      afterFields={answer && <ProposalChecks checks={answer.checks} />}
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
        <p className={styles.muted}>
          Samma kontroller som när uppfödaren registrerar kaninen.
        </p>
      }
    />
  );
}
