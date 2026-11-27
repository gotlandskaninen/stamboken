"use client";

import { useEffect, useId, useRef, useState, useTransition } from "react";
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
import { CoatChoice } from "@/components/herd/CoatChoice";
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
  type Proposal,
  type ProposedField,
  type SaveMode,
  type Source,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";
import styles from "@/app/(app)/stamboken/(dashboard)/inkorg/inkorg.module.css";
import report from "@/app/(app)/stamboken/(dashboard)/arsrapport/arsrapport.module.css";

/** One of the mother's litters, as the report's lookup gives them: picking it fills in the kit's litter. */
export type ParentLitter = {
  id: number;
  birth_date: string;
  father: string | null;
  litter_size: number | null;
  litter_size6w: number | null;
  /** The count alive at 6 weeks is only the count born, until someone confirms it. */
  preliminary?: boolean;
};
export type Found = RegistryRabbit & { litters?: ParentLitter[] };
/** The registry's record of a number: null when there is no such rabbit, undefined when the lookup could not tell. */
export type Lookup = (number: string) => Promise<Found | null | undefined>;
/** A refusal; `problem` null when the caller has shown it itself (the report's photo field). */
export type SaveResult = { ok: true } | { ok: false; problem: Problem | null };
/** "Var är kaninen nu" (spec 5.8). */
export type Where = "hos_mig" | "sald" | "dod";
export type Parent = "mother" | "father";
/** The yearly report's member, not the queue's handler: the report's rules, and its larger fields (labels above). */
export type Variant = "member";
export const COUNT_LEFT_EMPTY =
  "Står det inte på intyget, lämna tomt. Då räknas alla som levande tills du bekräftar antalet.";

/** What the reading saw and what the registry says, beside a field that is not simply läst; null otherwise. */
export function proposalHint(field?: ProposedField) {
  if (!field || field.source === "läst") return null;
  const parts = [
    field.read && `Inläst: ${field.read}`,
    field.registry != null && `Registret: ${field.registry}`,
  ].filter(Boolean);
  return parts.length ? (
    <span className={styles.registry}>{parts.join(" · ")}</span>
  ) : null;
}

/** The image reading's checks in words, under what they are about. */
export function ProposalChecks({ checks }: { checks: Proposal["checks"] }) {
  return checks.length > 0 ? (
    <ul className={styles.checks} aria-label="Kontroller">
      {checks.map((check) => (
        <li key={check.text} data-ok={String(check.ok)}>
          <span aria-hidden="true">
            {check.ok === true ? "✓" : check.ok === false ? "✗" : "·"}
          </span>{" "}
          {check.text}
        </li>
      ))}
    </ul>
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

// The rabbit row's words and order (RabbitRow's CHOICES)
const WHERE: [Where, string][] = [
  ["hos_mig", "Finns kvar"],
  ["dod", "Död"],
  ["sald", "Såld"],
];
const SEXES: [string, string][] = [
  ["female", "Hona"],
  ["male", "Hane"],
  ["", "Inte angivet"],
];
const ADD_PARENT: Record<Parent, string> = {
  mother: "Lägg till modern från hennes intyg nu",
  father: "Lägg till fadern från hans intyg nu",
};

const litterLabel = (l: ParentLitter) =>
  [
    `Född ${l.birth_date}`,
    l.father && `far ${l.father}`,
    l.litter_size != null && `${l.litter_size} födda`,
  ]
    .filter(Boolean)
    .join(", ");

/**
 * What a certificate shows, as one registration form for the queue and the
 * yearly report: the fields, the paper number's check (a conflict opens
 * NumberConflictDialog) and the registry's record of each number, looked up
 * with `lookup`. The caller owns the values (`form`) and saves with `onSave`.
 * The report adds its photo, the mother's litters (from its lookup) with the
 * number Stamboken suggests for the chosen one (`suggest`), "var är kaninen
 * nu" and a missing parent's own registration.
 */
export function RegisterFromCertificate({
  mode,
  variant,
  form,
  onChange,
  rex = false,
  onRexChange,
  colors,
  lookup,
  onSave,
  canSave,
  beforeSubmit,
  submitLabel,
  conflictHint,
  proposed = {},
  photo,
  where,
  onWhere,
  onAddParent,
  suggest,
  header,
  afterFields,
  buttons,
  footer,
}: {
  mode: SaveMode;
  variant?: Variant;
  form: CertForm;
  onChange: (key: keyof CertForm, value: string) => void;
  rex?: boolean;
  onRexChange?: (rex: boolean) => void;
  colors: string[];
  lookup: Lookup;
  onSave: (payload: Record<string, unknown>) => Promise<SaveResult>;
  canSave: boolean;
  /** On Spara, before the browser's own checks: false stops the save, and the caller shows why. */
  beforeSubmit?: () => boolean;
  submitLabel: string;
  /** Under the form when the paper's number is refused: what to do if the paper is right. */
  conflictHint: string;
  proposed?: Partial<Record<keyof CertForm, ProposedField>>;
  photo?: React.ReactNode;
  where?: Where | null;
  onWhere?: (where: Where) => void;
  onAddParent?: (parent: Parent, number: string) => void;
  /** The individual number Stamboken would give a certificate of the litter, or null. */
  suggest?: (litterId: number) => Promise<string | null>;
  header?: React.ReactNode;
  afterFields?: React.ReactNode;
  /** Beside Spara; a function gets whether a save is in progress. */
  buttons?: React.ReactNode | ((pending: boolean) => React.ReactNode);
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
  const member = variant === "member";
  const sexName = useId();
  const registry = {
    individual: useRegistry(
      mode === "pappersintyg" ? form.individual : "",
      lookup,
    ),
    mother: useRegistry(mode === "ny_kanin" ? form.mother : "", lookup),
    father: useRegistry(mode === "ny_kanin" ? form.father : "", lookup),
  };
  const litters = registry.mother?.litters ?? [];
  const picked = litters.find(
    (l) =>
      l.birth_date === form.birth_date &&
      (l.father ?? "") === form.father.trim().toUpperCase(),
  );

  const submit = (resolution?: NumberResolution) =>
    start(async () => {
      setErrors({});
      setFormError(null);
      const res = await onSave(buildSavePayload(mode, form, resolution, rex));
      if (res.ok) {
        setConflict(null);
        return;
      }
      const problem = res.problem;
      if (!problem) return;
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

  // The number Stamboken suggests for the chosen litter: shown, and filled in where nothing is typed yet or where
  // an earlier suggestion filled it. An answer counts only while it is the latest asked for and its litter is still
  // the chosen one; a number the user typed is never replaced.
  const [suggested, setSuggested] = useState<{
    litter: number;
    number: string;
  } | null>(null);
  const now = useRef({ number: form.paper_number, litter: picked?.id });
  useEffect(() => {
    now.current = { number: form.paper_number, litter: picked?.id };
  });
  const asked = useRef(0);
  const filled = useRef<string | null>(null);
  const pickLitter = (id: string) => {
    const request = ++asked.current;
    const l = litters.find((x) => String(x.id) === id);
    if (!l) {
      // "Annan kull": the chosen litter's values go, so another litter can be typed
      for (const key of [
        "birth_date",
        "father",
        "litter_size",
        "litter_size6w",
      ] as const)
        onChange(key, "");
      return;
    }
    onChange("birth_date", l.birth_date);
    onChange("father", l.father ?? "");
    onChange("litter_size", l.litter_size == null ? "" : String(l.litter_size));
    // A preliminary count is the count born: the certificate's own count is asked for, not copied from it
    onChange(
      "litter_size6w",
      l.litter_size6w == null || l.preliminary ? "" : String(l.litter_size6w),
    );
    suggest?.(l.id).then((number) => {
      if (!number || request !== asked.current || now.current.litter !== l.id)
        return;
      setSuggested({ litter: l.id, number });
      const typed = now.current.number.trim();
      if (typed && typed !== filled.current) return;
      filled.current = number;
      onChange("paper_number", number);
    });
  };
  const suggestion =
    suggested && picked?.id === suggested.litter ? suggested.number : null;

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
  ) => (
    <>
      {text(key, label, {
        required,
        placeholder: "G1274-2512",
        helperText: <RegistryHint rabbit={registry[key]} />,
      })}
      {key !== "individual" && registry[key] === null && onAddParent && (
        <div className={styles.field}>
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            onClick={() => onAddParent(key, form[key].trim().toUpperCase())}
          >
            {ADD_PARENT[key]}
          </button>
        </div>
      )}
    </>
  );

  return (
    <form
      className={`${styles.card} ${member ? report.memberFields : ""}`}
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      {header}
      {photo}

      <div className={styles.fields}>
        {mode === "pappersintyg" &&
          number("individual", "Individnummer i Stamboken")}
        {text("paper_number", "Individnummer på pappret", {
          required: true,
          placeholder: "G1274-2512",
          // Under what the reading saw, "as on the certificate" reads as a caption of it.
          helperText: [
            !proposalHint(proposed.paper_number) && "Som det står på intyget.",
            suggestion && `Stamboken föreslår ${suggestion}.`,
          ]
            .filter(Boolean)
            .join(" "),
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
            {member ? (
              // the report's choices, not a menu: Hona and Hane at a tap
              <Field source={sources.sex}>
                <fieldset className={report.choiceSet}>
                  <legend className={report.label}>Kön</legend>
                  <div className={report.choices}>
                    {SEXES.map(([value, label]) => (
                      <label key={value} className={report.choice}>
                        <input
                          type="radio"
                          name={sexName}
                          checked={form.sex === value}
                          onChange={() => onChange("sex", value)}
                        />
                        <span>{label}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              </Field>
            ) : (
              text("sex", "Kön", {
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
              })
            )}
            {onRexChange && <CoatChoice rex={rex} onChange={onRexChange} />}
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
            {litters.length > 0 && (
              <Field>
                <TextField
                  select
                  label="Kull"
                  size="small"
                  fullWidth
                  value={picked ? String(picked.id) : ""}
                  onChange={(e) => pickLitter(e.target.value)}
                  helperText="En vald kull fyller i födelsedatum, far och antal."
                >
                  <MenuItem value="">Annan kull</MenuItem>
                  {litters.map((l) => (
                    <MenuItem key={l.id} value={String(l.id)}>
                      {litterLabel(l)}
                    </MenuItem>
                  ))}
                </TextField>
              </Field>
            )}
            {number("father", "Far")}
            {text("litter_size", "Antal födda", {
              type: "number",
              slotProps: { htmlInput: { min: 1 } },
            })}
            {text("litter_size6w", "Levande i kullen efter 6 veckor", {
              type: "number",
              slotProps: { htmlInput: { min: 1 } },
              required: !!picked?.preliminary,
              helperText: picked?.preliminary
                ? "Kullens antal är preliminärt. Skriv antalet som står på intyget."
                : variant === "member" && !picked
                  ? COUNT_LEFT_EMPTY // a new litter's empty count is the count born, preliminary (as Lägg till kull)
                  : "Står inte alltid på intyget.",
            })}
            {onWhere && (
              <Field wide>
                <fieldset className={report.choiceSet}>
                  <legend className={report.label}>Var är kaninen nu?</legend>
                  <div className={report.choices}>
                    {WHERE.map(([value, label]) => (
                      <label key={value} className={report.choice}>
                        <input
                          type="radio"
                          name="where"
                          checked={where === value}
                          onChange={() => onWhere(value)}
                        />
                        <span>{label}</span>
                      </label>
                    ))}
                  </div>
                </fieldset>
              </Field>
            )}
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
        <button
          type="submit"
          className="sb-btn"
          disabled={!canSave || pending}
          onClick={(e) => {
            if (beforeSubmit && !beforeSubmit()) e.preventDefault();
          }}
        >
          {pending ? "Sparar…" : submitLabel}
        </button>
        {typeof buttons === "function" ? buttons(pending) : buttons}
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
