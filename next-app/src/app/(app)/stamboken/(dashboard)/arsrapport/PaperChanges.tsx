"use client";

import React from "react";
import { MbCard } from "../min-besattning/min-besattning-ui";
import { CONSENT_TEXT, UTOM_ALL, type PaperFields, type Utom } from "./lib";
import styles from "./arsrapport.module.css";

const UTOM_LABEL: Record<Utom, string> = {
  phone: "telefonnummer",
  email: "e-postadress",
  address: "postnummer och ort",
};

// The form's contact part. The page never reads the stored values: it shows
// only the last two digits of the account (`accountEnd`), and what is typed
// here goes to the matrikel when the form is sent. Its state is the caller's,
// outside FormState, so it never reaches a draft or localStorage.
export function PaperChanges({
  fields,
  onChange,
  emailError,
  accountEnd,
}: {
  fields: PaperFields;
  onChange: (f: PaperFields) => void;
  emailError?: string;
  accountEnd: string | null;
}) {
  const set = (patch: Partial<PaperFields>) =>
    onChange({ ...fields, ...patch });
  const text = (
    label: string,
    value: string,
    apply: (v: string) => void,
    extra: React.InputHTMLAttributes<HTMLInputElement> = {},
  ) => (
    <label className={styles.label}>
      {label}
      <input
        className={styles.field}
        style={{ width: "100%", boxSizing: "border-box" }}
        autoComplete="off"
        value={value}
        onChange={(e) => apply(e.target.value)}
        {...extra}
      />
    </label>
  );
  const digits = fields.konto.konto.replace(/\D/g, "");
  const sameEnd =
    !!accountEnd && digits.length >= 2 && digits.endsWith(accountEnd);

  return (
    <MbCard title="Uppgifter på blanketten">
      <div className={styles.detail}>
        <div role="radiogroup" aria-label="Publicering i Koharen">
          <p className={styles.label} style={{ margin: "0 0 8px" }}>
            {CONSENT_TEXT}
          </p>
          <div className={styles.choices}>
            {(
              [
                ["ja", "Ja"],
                ["nej", "Nej"],
                ["", "Inget svar på blanketten"],
              ] as const
            ).map(([v, label]) => (
              <label key={v || "inget"} className={styles.choice}>
                <input
                  type="radio"
                  name="consent"
                  checked={fields.consent === v}
                  onChange={() =>
                    set({ consent: v, utom: v === "ja" ? UTOM_ALL : [] })
                  }
                />
                <span>{label}</span>
              </label>
            ))}
          </div>
        </div>
        {fields.consent === "ja" && (
          <div role="group" aria-label="Får stå med">
            <span className={styles.label}>
              Om ja står ditt namn och besättningens nummer med. Kryssa också
              det ur medlemsregistret som får stå med:
            </span>
            {(Object.keys(UTOM_LABEL) as Utom[]).map((k) => (
              <label key={k} className={styles.line} style={{ minHeight: 48 }}>
                <input
                  type="checkbox"
                  checked={!fields.utom.includes(k)}
                  onChange={(e) =>
                    set({
                      utom: e.target.checked
                        ? fields.utom.filter((x) => x !== k)
                        : [...fields.utom, k],
                    })
                  }
                />
                {UTOM_LABEL[k]}
              </label>
            ))}
          </div>
        )}
        <p className={styles.label} style={{ margin: 0 }}>
          Kryssar du varken ja eller nej gäller ditt senaste svar. Har du aldrig
          svarat publicerar vi ingenting. Du kan ändra ditt svar när som helst i
          Stamboken Online eller hos genbanksansvarig.
        </p>

        {text("E-post", fields.epost, (v) => set({ epost: v }), {
          id: "paper-email",
          type: "email",
          inputMode: "email",
          maxLength: 255,
          "aria-invalid": emailError ? true : undefined,
          "aria-describedby": emailError ? "paper-email-error" : undefined,
        })}
        {emailError && (
          <p id="paper-email-error" className={styles.errorText}>
            {emailError}
          </p>
        )}
        {text("Telefon", fields.telefon, (v) => set({ telefon: v }), {
          type: "tel",
          maxLength: 50,
        })}

        <p className={styles.label} style={{ margin: 0 }}>
          {accountEnd
            ? `Nuvarande konto slutar på ••${accountEnd}`
            : "Inget konto i matrikeln"}
        </p>
        {text(
          "Clearingnummer",
          fields.konto.clearing,
          (v) => set({ konto: { ...fields.konto, clearing: v } }),
          { inputMode: "numeric", maxLength: 12 },
        )}
        {text(
          "Kontonummer",
          fields.konto.konto,
          (v) => set({ konto: { ...fields.konto, konto: v } }),
          { inputMode: "numeric", maxLength: 20 },
        )}
        {sameEnd && (
          <p className={styles.note} role="status">
            Samma slutsiffror som nuvarande konto. Är det samma konto? Lämna då
            fälten tomma.
          </p>
        )}
        {text(
          "Bank",
          fields.konto.bank,
          (v) => set({ konto: { ...fields.konto, bank: v } }),
          { maxLength: 100 },
        )}

        {text(
          "Gatuadress",
          fields.adress.address,
          (v) => set({ adress: { ...fields.adress, address: v } }),
          { maxLength: 200 },
        )}
        {text(
          "Postnummer",
          fields.adress.postal_code,
          (v) => set({ adress: { ...fields.adress, postal_code: v } }),
          { inputMode: "numeric", maxLength: 10 },
        )}
        {text(
          "Ort",
          fields.adress.city,
          (v) => set({ adress: { ...fields.adress, city: v } }),
          { maxLength: 100 },
        )}

        <p className={styles.note}>
          Ändringarna sparas direkt i matrikeln. Tomma fält ändrar ingenting.
        </p>
      </div>
    </MbCard>
  );
}
