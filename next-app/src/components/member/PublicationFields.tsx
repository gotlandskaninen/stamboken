"use client";

import { useId } from "react";
import {
  CONSENT_TEXT,
  UTOM_ALL,
  type Utom,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";
import styles from "@/app/(app)/stamboken/(dashboard)/arsrapport/arsrapport.module.css";

// The answer to the Koharen question (spec 5.11): Ja or Nej, and at Ja what is left out.
export type Publication = { ja: boolean; utom: Utom[] };

const UTOM_LABEL: Record<Utom, string> = {
  phone: "telefonnummer",
  email: "e-postadress",
  address: "postnummer och ort",
};

// The Koharen question, the same on the paper form, in the profile and in the
// report. `null` is no answer: nothing is chosen. `noAnswer` adds a choice that
// gives null (the paper form's "no answer on the form").
export function PublicationFields({
  value,
  onChange,
  disabled,
  noAnswer,
}: {
  value: Publication | null;
  onChange: (value: Publication | null) => void;
  disabled?: boolean;
  noAnswer?: string;
}) {
  const name = useId();
  const chosen = value === null ? "" : value.ja ? "ja" : "nej";
  const choices: [string, string][] = [
    ["ja", "Ja"],
    ["nej", "Nej"],
    ...(noAnswer ? [["", noAnswer] as [string, string]] : []),
  ];
  return (
    <>
      <div role="radiogroup" aria-label="Publicering i Koharen">
        <p className={styles.label} style={{ margin: "0 0 8px" }}>
          {CONSENT_TEXT}
        </p>
        <div className={styles.choices}>
          {choices.map(([v, label]) => (
            <label key={v || "inget"} className={styles.choice}>
              <input
                type="radio"
                name={name}
                checked={chosen === v}
                disabled={disabled}
                onChange={() =>
                  // The form asks what may appear: at Ja nothing is ticked at first.
                  onChange(
                    v
                      ? { ja: v === "ja", utom: v === "ja" ? UTOM_ALL : [] }
                      : null,
                  )
                }
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </div>
      {value?.ja && (
        <div role="group" aria-label="Får stå med">
          <span className={styles.label}>
            Om ja står ditt namn och besättningens nummer med. Kryssa också det
            ur medlemsregistret som får stå med:
          </span>
          {UTOM_ALL.map((k) => (
            <label key={k} className={styles.line} style={{ minHeight: 48 }}>
              <input
                type="checkbox"
                checked={!value.utom.includes(k)}
                disabled={disabled}
                onChange={(e) =>
                  onChange({
                    ja: true,
                    utom: e.target.checked
                      ? value.utom.filter((x) => x !== k)
                      : [...value.utom, k],
                  })
                }
              />
              {UTOM_LABEL[k]}
            </label>
          ))}
        </div>
      )}
    </>
  );
}
