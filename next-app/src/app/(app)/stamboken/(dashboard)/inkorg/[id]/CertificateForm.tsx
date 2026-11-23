"use client";

import { useState } from "react";
import {
  Field,
  proposalHint,
  ProposalChecks,
  RegisterFromCertificate,
} from "@/components/register/RegisterFromCertificate";
import { lookupRabbit, saveCertificate } from "../actions";
import {
  initialCertForm,
  initialSaveMode,
  shownProposal,
  type CertForm,
  type InboxDocument,
  type Proposal,
  type SaveMode,
} from "../lib";
import styles from "../inkorg.module.css";

const GRANDPARENTS = [
  ["farfar", "Farfar"],
  ["farmor", "Farmor"],
  ["morfar", "Morfar"],
  ["mormor", "Mormor"],
] as const;

/**
 * What a certificate shows, saved with …/spara: a new rabbit, or the paper
 * certificate on a rabbit that exists. Every field starts empty or from the
 * image reading's proposal, coloured by where its value came from, with the
 * proposal's checks under the fields. Nothing is saved until Spara. The form
 * itself is RegisterFromCertificate, shared with the yearly report.
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
  // is never replaced: an untouched form takes the proposal, a touched one is
  // offered it ("Fyll i förslaget").
  const latest = shownProposal(doc);
  const [applied, setApplied] = useState(latest !== null);
  const [touched, setTouched] = useState(false);
  const proposal = applied ? latest : null;
  const proposed = proposal?.fields ?? {};
  const [mode, setModeState] = useState<SaveMode>(() =>
    initialSaveMode(latest),
  );
  const [form, setForm] = useState<CertForm>(() => initialCertForm(latest));
  const [rex, setRex] = useState(false);
  const setMode = (value: SaveMode) => {
    setTouched(true);
    setModeState(value);
  };
  const set = (key: keyof CertForm, value: string) => {
    setTouched(true);
    setForm((f) => ({ ...f, [key]: value }));
  };
  const fill = (p: Proposal) => {
    setForm(initialCertForm(p));
    setModeState(initialSaveMode(p));
    setApplied(true);
  };
  if (!latest && applied) setApplied(false);
  if (latest && !applied && !touched) fill(latest);

  return (
    <RegisterFromCertificate
      mode={mode}
      form={form}
      onChange={set}
      rex={rex}
      onRexChange={(value) => {
        setTouched(true);
        setRex(value);
      }}
      colors={colors}
      lookup={lookupRabbit}
      proposed={proposed}
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
              Fotot tolkas. Förslaget kommer om några minuter; ladda om sidan
              då.
            </p>
          )}
          {doc.interpretation_status === "misslyckad" && (
            <p className={styles.muted}>
              Fotot gick inte att tolka. Skriv av fälten, eller vrid fotot rätt
              och klicka Tolka igen.
            </p>
          )}
          {latest && !applied && (
            <p className={styles.note}>
              Det finns ett förslag från tolkningen.{" "}
              <button
                type="button"
                className="sb-btn sb-btn-secondary sb-btn-sm"
                onClick={() => fill(latest)}
              >
                Fyll i förslaget
              </button>
            </p>
          )}
          {proposal && (
            <p className={styles.note}>
              Förslag från bildtolkningen. Jämför varje fält med fotot innan du
              sparar. Fält som avviker från registret eller är osäkra är tomma:
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
      afterFields={
        proposal && (
          <>
            {mode === "ny_kanin" &&
              GRANDPARENTS.some(([key]) => proposed[key]) && (
                <ul
                  className={styles.checks}
                  aria-label="Far- och morföräldrar"
                >
                  {GRANDPARENTS.filter(([key]) => proposed[key]).map(
                    ([key, label]) => (
                      <li key={key}>
                        <Field source={proposed[key]?.source}>
                          {label}: {proposed[key]?.value ?? "–"}
                          {proposalHint(proposed[key])}
                        </Field>
                      </li>
                    ),
                  )}
                </ul>
              )}
            <ProposalChecks checks={proposal.checks} />
          </>
        )
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
        <p className={styles.muted}>
          Samma kontroller som när uppfödaren registrerar kaninen.
        </p>
      }
    />
  );
}
