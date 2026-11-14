"use client";

import { useEffect, useState, useTransition } from "react";
import {
  Autocomplete,
  MenuItem,
  TextField,
  type TextFieldProps,
} from "@mui/material";
import {
  NumberConflictDialog,
  PAPER_NUMBER,
} from "@/components/herd/NumberConflictDialog";
import type { NumberCheck } from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";
import { lookupRabbit, saveCertificate, type RegistryRabbit } from "../actions";
import {
  buildSavePayload,
  initialCertForm,
  initialSaveMode,
  numberCheckOf,
  problemField,
  problemText,
  shownProposal,
  type CertForm,
  type InboxDocument,
  type NumberResolution,
  type ProposedField,
  type SaveMode,
  type Source,
} from "../lib";
import styles from "../inkorg.module.css";

const GRANDPARENTS = [
  ["farfar", "Farfar"],
  ["farmor", "Farmor"],
  ["morfar", "Morfar"],
  ["mormor", "Mormor"],
] as const;

/** What the reading saw and what the registry says, beside a field that is not simply läst; null otherwise. */
function proposalHint(field?: ProposedField) {
  if (!field || field.source === "läst") return null;
  const parts = [
    field.read && `Intyget: ${field.read}`,
    field.registry != null && `Registret: ${field.registry}`,
  ].filter(Boolean);
  return parts.length ? (
    <span className={styles.registry}>{parts.join(" · ")}</span>
  ) : null;
}

function Field({
  source,
  wide,
  children,
}: {
  source?: Source;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div
      className={`${styles.field} ${wide ? styles.wide : ""}`}
      data-source={source}
    >
      {children}
      {source && <span className={styles.sourceTag}>{source}</span>}
    </div>
  );
}

/** The registry's record of a number, to compare with the photo. */
function RegistryHint({ number }: { number: string }) {
  const wanted = number.trim().toUpperCase();
  const valid = PAPER_NUMBER.test(wanted);
  const [result, setResult] = useState<{
    number: string;
    rabbit: RegistryRabbit | null;
  } | null>(null);
  useEffect(() => {
    if (!valid) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const rabbit = await lookupRabbit(wanted);
      if (!cancelled) setResult({ number: wanted, rabbit });
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [wanted, valid]);
  if (!valid || result?.number !== wanted) return null;
  const { rabbit } = result;
  // A span: it sits in the field's helper text, which is a <p>.
  if (!rabbit)
    return <span className={styles.registry}>Finns inte i Stamboken.</span>;
  const parent = (label: string, p: RegistryRabbit["mother"]) =>
    p ? `${label} ${p.number}${p.name ? ` ${p.name}` : ""}` : null;
  const parts = [
    rabbit.name,
    rabbit.color,
    parent("mor", rabbit.mother),
    parent("far", rabbit.father),
  ];
  return (
    <span className={styles.registry}>
      Registret: {parts.filter(Boolean).join(" · ")}
    </span>
  );
}

/**
 * What a certificate shows, saved with …/spara: a new rabbit, or the paper
 * certificate on a rabbit that exists. Every field starts empty or from the
 * image reading's proposal, coloured by where its value came from, with the
 * proposal's checks under the fields. Nothing is saved until Spara.
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
  const proposal = shownProposal(doc);
  const proposed = proposal?.fields ?? {};
  const sources = Object.fromEntries(
    Object.entries(proposed).map(([key, field]) => [key, field?.source]),
  ) as Partial<Record<keyof CertForm, Source>>;
  const [mode, setMode] = useState<SaveMode>(() => initialSaveMode(proposal));
  const [form, setForm] = useState<CertForm>(() => initialCertForm(proposal));
  const [errors, setErrors] = useState<Partial<Record<keyof CertForm, string>>>(
    {},
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<NumberCheck | null>(null);
  const [pending, start] = useTransition();
  const set = (key: keyof CertForm, value: string) =>
    setForm((f) => ({ ...f, [key]: value }));

  const submit = (resolution?: NumberResolution) =>
    start(async () => {
      setErrors({});
      setFormError(null);
      const res = await saveCertificate(
        itemId,
        doc.id,
        buildSavePayload(mode, form, resolution),
      );
      if (res.ok) {
        setConflict(null);
        onSaved(res.data.document);
        return;
      }
      const problem = res.problem;
      // pappersintyg takes no resolution: there the conflict is only shown.
      setConflict(mode === "ny_kanin" ? numberCheckOf(problem) : null);
      const field = problemField(problem);
      // Next to the field when this mode shows it, else above the buttons.
      const shown =
        mode === "pappersintyg"
          ? ["individual", "paper_number", "paper_certificate"]
          : Object.keys(form).filter((k) => k !== "individual");
      if (field && shown.includes(field))
        setErrors({ [field]: problemText(problem) });
      else setFormError(problemText(problem));
    });

  const text = (
    key: keyof CertForm,
    label: string,
    props: TextFieldProps = {},
    wide = false,
  ) => {
    const hint = proposalHint(proposed[key]);
    return (
      <Field source={sources[key]} wide={wide}>
        <TextField
          label={label}
          value={form[key]}
          onChange={(e) => set(key, e.target.value)}
          error={!!errors[key]}
          size="small"
          fullWidth
          {...props}
          helperText={
            errors[key] ??
            (hint ? (
              <>
                {hint}
                {props.helperText}
              </>
            ) : (
              props.helperText
            ))
          }
        />
      </Field>
    );
  };
  const number = (key: keyof CertForm, label: string, required = true) =>
    text(key, label, {
      required,
      placeholder: "G1274-2512",
      helperText: <RegistryHint number={form[key]} />,
    });

  return (
    <form
      className={styles.card}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <h2 className={styles.cardTitle}>Det intyget visar</h2>
      {doc.interpretation_status === "vantar" && (
        <p className={styles.muted}>
          Fotot tolkas. Förslaget kommer om några minuter; ladda om sidan då.
        </p>
      )}
      {doc.interpretation_status === "misslyckad" && (
        <p className={styles.muted}>
          Fotot gick inte att tolka. Skriv av fälten, eller vrid fotot rätt och
          klicka Tolka igen.
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

      <div className={styles.fields}>
        {mode === "pappersintyg" &&
          number("individual", "Individnummer i Stamboken")}
        {text("paper_number", "Individnummer på pappret", {
          required: true,
          placeholder: "G1274-2512",
          helperText: "Som det står på intyget.",
        })}
        {text("paper_certificate", "Intygsnummer", {
          required: true,
          slotProps: { htmlInput: { maxLength: 20 } },
        })}
        {mode === "ny_kanin" && (
          <>
            {text("name", "Namn", {
              slotProps: { htmlInput: { maxLength: 50 } },
            })}
            {text("sex", "Kön", {
              select: true,
              children: [
                <MenuItem key="" value="">
                  Inte angivet
                </MenuItem>,
                <MenuItem key="female" value="female">
                  Hona
                </MenuItem>,
                <MenuItem key="male" value="male">
                  Hane
                </MenuItem>,
              ],
            })}
            {text("birth_date", "Födelsedatum", {
              required: true,
              type: "date",
              slotProps: { inputLabel: { shrink: true } },
            })}
            <Field source={sources.color}>
              <Autocomplete
                options={colors}
                freeSolo={colors.length === 0}
                value={form.color || null}
                onChange={(_, v) => set("color", v ?? "")}
                onInputChange={
                  colors.length === 0 ? (_, v) => set("color", v) : undefined
                }
                renderInput={(params) => (
                  <TextField
                    {...params}
                    label="Färg"
                    size="small"
                    error={!!errors.color}
                    helperText={errors.color ?? proposalHint(proposed.color)}
                  />
                )}
              />
            </Field>
            {number("mother", "Mor")}
            {number("father", "Far")}
            {text("litter_size", "Antal födda", {
              type: "number",
              slotProps: { htmlInput: { min: 1 } },
            })}
            {text("litter_size6w", "Levande i kullen efter 6 veckor", {
              type: "number",
              slotProps: { htmlInput: { min: 1 } },
              helperText: "Står inte alltid på intyget.",
            })}
          </>
        )}
      </div>

      {proposal && (
        <>
          {mode === "ny_kanin" &&
            GRANDPARENTS.some(([key]) => proposed[key]) && (
              <ul className={styles.checks} aria-label="Far- och morföräldrar">
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
          {proposal.checks.length > 0 && (
            <ul className={styles.checks} aria-label="Kontroller">
              {proposal.checks.map((check) => (
                <li key={check.text} data-ok={String(check.ok)}>
                  <span aria-hidden="true">
                    {check.ok === true ? "✓" : check.ok === false ? "✗" : "·"}
                  </span>{" "}
                  {check.text}
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {formError && (
        <p role="alert" className={styles.error}>
          {formError}
        </p>
      )}
      {errors.paper_number && (
        <p className={styles.muted}>
          Stämmer pappret? Lämna ärendet till genbanksansvarig.
        </p>
      )}
      <div className={styles.submitRow}>
        <button type="submit" className="sb-btn" disabled={!canSave || pending}>
          {pending ? "Sparar…" : "Spara och nästa"}
        </button>
        <button
          type="button"
          className="sb-btn sb-btn-secondary"
          onClick={onSkip}
        >
          Hoppa över
        </button>
      </div>
      <p className={styles.muted}>
        Samma kontroller som när uppfödaren registrerar kaninen.
      </p>

      {conflict && (
        <NumberConflictDialog
          check={conflict}
          isSaving={pending}
          onUseStambokenNumber={() =>
            submit({
              expected_number: conflict.stamboken_number,
              choice: "use_stamboken_number",
            })
          }
          onClose={() => setConflict(null)}
        />
      )}
    </form>
  );
}
