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
import type { RegistryRabbit } from "@/app/(app)/stamboken/(dashboard)/inkorg/actions";
import {
  buildSavePayload,
  numberCheckOf,
  problemField,
  problemText,
  type CertForm,
  type NumberResolution,
  type Problem,
  type ProposedField,
  type SaveMode,
  type Source,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";
import styles from "@/app/(app)/stamboken/(dashboard)/inkorg/inkorg.module.css";

export type Found = RegistryRabbit;
/** The registry's record of a number: null when there is no such rabbit, undefined when the lookup could not tell. */
export type Lookup = (number: string) => Promise<Found | null | undefined>;
export type SaveResult = { ok: true } | { ok: false; problem: Problem };

/** What the reading saw and what the registry says, beside a field that is not simply läst; null otherwise. */
export function proposalHint(field?: ProposedField) {
  if (!field || field.source === "läst") return null;
  const parts = [
    field.read && `Intyget: ${field.read}`,
    field.registry != null && `Registret: ${field.registry}`,
  ].filter(Boolean);
  return parts.length ? (
    <span className={styles.registry}>{parts.join(" · ")}</span>
  ) : null;
}

/** A field coloured by where its value came from (the queue's image reading). */
export function Field({
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

/** The registry's record of `number` once it looks like one ("" looks up nothing). */
function useRegistry(number: string, lookup: Lookup) {
  const wanted = number.trim().toUpperCase();
  const valid = PAPER_NUMBER.test(wanted);
  const [result, setResult] = useState<{
    number: string;
    rabbit: Found | null | undefined;
  } | null>(null);
  useEffect(() => {
    if (!valid) return;
    let cancelled = false;
    const timer = setTimeout(async () => {
      const rabbit = await lookup(wanted);
      if (!cancelled) setResult({ number: wanted, rabbit });
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [wanted, valid, lookup]);
  return valid && result?.number === wanted ? result.rabbit : undefined;
}

/** The registry's record of a number, to compare with the photo. */
function RegistryHint({ rabbit }: { rabbit: Found | null | undefined }) {
  if (rabbit === undefined) return null;
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
 * What a certificate shows, as one registration form for the queue and the
 * yearly report: the fields, the paper number's check (a conflict opens
 * NumberConflictDialog) and the registry's record of each number, looked up
 * with `lookup`. The caller owns the values (`form`) and saves with `onSave`.
 */
export function RegisterFromCertificate({
  mode,
  form,
  onChange,
  colors,
  lookup,
  onSave,
  canSave,
  submitLabel,
  conflictHint,
  proposed = {},
  header,
  afterFields,
  buttons,
  footer,
}: {
  mode: SaveMode;
  form: CertForm;
  onChange: (key: keyof CertForm, value: string) => void;
  colors: string[];
  lookup: Lookup;
  onSave: (payload: Record<string, unknown>) => Promise<SaveResult>;
  canSave: boolean;
  submitLabel: string;
  /** Under the form when the paper's number is refused: what to do if the paper is right. */
  conflictHint: string;
  proposed?: Partial<Record<keyof CertForm, ProposedField>>;
  header?: React.ReactNode;
  afterFields?: React.ReactNode;
  buttons?: React.ReactNode;
  footer?: React.ReactNode;
}) {
  const sources = Object.fromEntries(
    Object.entries(proposed).map(([key, field]) => [key, field?.source]),
  ) as Partial<Record<keyof CertForm, Source>>;
  const [errors, setErrors] = useState<Partial<Record<keyof CertForm, string>>>(
    {},
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [conflict, setConflict] = useState<NumberCheck | null>(null);
  const [pending, start] = useTransition();
  const registry = {
    individual: useRegistry(
      mode === "pappersintyg" ? form.individual : "",
      lookup,
    ),
    mother: useRegistry(mode === "ny_kanin" ? form.mother : "", lookup),
    father: useRegistry(mode === "ny_kanin" ? form.father : "", lookup),
  };
  const submit = (resolution?: NumberResolution) =>
    start(async () => {
      setErrors({});
      setFormError(null);
      const res = await onSave(buildSavePayload(mode, form, resolution));
      if (res.ok) {
        setConflict(null);
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
          onChange={(e) => onChange(key, e.target.value)}
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
  const number = (
    key: "individual" | "mother" | "father",
    label: string,
    required = true,
  ) =>
    text(key, label, {
      required,
      placeholder: "G1274-2512",
      helperText: <RegistryHint rabbit={registry[key]} />,
    });

  return (
    <form
      className={styles.card}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {header}

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
                onChange={(_, v) => onChange("color", v ?? "")}
                onInputChange={
                  colors.length === 0
                    ? (_, v) => onChange("color", v)
                    : undefined
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

      {afterFields}

      {formError && (
        <p role="alert" className={styles.error}>
          {formError}
        </p>
      )}
      {errors.paper_number && <p className={styles.muted}>{conflictHint}</p>}
      <div className={styles.submitRow}>
        <button type="submit" className="sb-btn" disabled={!canSave || pending}>
          {pending ? "Sparar…" : submitLabel}
        </button>
        {buttons}
      </div>
      {footer}

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
