"use client";

import React from "react";
import { PublicationFields } from "@/components/member/PublicationFields";
import { MbCard } from "../min-besattning/min-besattning-ui";
import { type KontoTyp, type PaperFields } from "./lib";
import styles from "./arsrapport.module.css";

const KONTO_TYP: [KontoTyp, string][] = [
  ["bankkonto", "Bankkonto"],
  ["bankgiro", "Bankgiro"],
  ["plusgiro", "Plusgiro"],
];

// A labelled text field of "Dina uppgifter", on paper and in the report.
export function TextField({
  label,
  ...input
}: React.InputHTMLAttributes<HTMLInputElement> & { label: string }) {
  return (
    <label className={styles.label}>
      {label}
      <input
        className={styles.field}
        style={{ width: "100%", boxSizing: "border-box" }}
        autoComplete="off"
        {...input}
      />
    </label>
  );
}

export const textField = (
  label: string,
  value: string,
  apply: (v: string) => void,
  extra: React.InputHTMLAttributes<HTMLInputElement> = {},
) => (
  <TextField
    label={label}
    value={value}
    onChange={(e) => apply(e.target.value)}
    {...extra}
  />
);

type Konto = PaperFields["konto"];

// A new support account: its type (drift #53), the clearing number for a bankkonto only, the number and the bank.
// With `accountEnd` it says when the typed number ends as the stored one does.
export function AccountFields({
  konto,
  onChange,
  accountEnd,
}: {
  konto: Konto;
  onChange: (k: Konto) => void;
  accountEnd?: string | null;
}) {
  const set = (patch: Partial<Konto>) => onChange({ ...konto, ...patch });
  const digits = konto.konto.replace(/\D/g, "");
  const sameEnd =
    !!accountEnd && digits.length >= 2 && digits.endsWith(accountEnd);
  return (
    <>
      <div role="radiogroup" aria-label="Typ av konto">
        <div className={styles.choices}>
          {KONTO_TYP.map(([v, label]) => (
            <label key={v} className={styles.choice}>
              <input
                type="radio"
                name="kontotyp"
                checked={konto.typ === v}
                onChange={() =>
                  // only a bankkonto has a clearing number
                  set({
                    typ: v,
                    clearing: v === "bankkonto" ? konto.clearing : "",
                  })
                }
              />
              <span>{label}</span>
            </label>
          ))}
        </div>
      </div>
      {(konto.typ === "" || konto.typ === "bankkonto") &&
        textField(
          "Clearingnummer",
          konto.clearing,
          (v) => set({ clearing: v }),
          { inputMode: "numeric", maxLength: 12 },
        )}
      {textField("Kontonummer", konto.konto, (v) => set({ konto: v }), {
        inputMode: "numeric",
        maxLength: 20,
      })}
      {sameEnd && (
        <p className={styles.note} role="status">
          Samma slutsiffror som nuvarande konto. Är det samma konto? Lämna då
          fälten tomma.
        </p>
      )}
      {textField("Bank", konto.bank, (v) => set({ bank: v }), {
        maxLength: 100,
      })}
    </>
  );
}

// The form's contact part. The page never reads the stored values: it shows
// only the last two digits of the account (`accountEnd`, "" when the number
// is too short to show any, null when there is none), and what is typed
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

  return (
    <MbCard title="Uppgifter på blanketten">
      <div className={styles.detail}>
        <PublicationFields
          value={
            fields.consent
              ? { ja: fields.consent === "ja", utom: fields.utom }
              : null
          }
          onChange={(v) =>
            set(
              v
                ? { consent: v.ja ? "ja" : "nej", utom: v.utom }
                : { consent: "", utom: [] },
            )
          }
          noAnswer="Inget svar på blanketten"
        />
        <p className={styles.label} style={{ margin: 0 }}>
          Kryssar du varken ja eller nej gäller ditt senaste svar. Har du aldrig
          svarat publicerar vi ingenting. Du kan ändra ditt svar när som helst i
          Stamboken Online eller hos genbanksansvarig.
        </p>

        {textField("E-post", fields.epost, (v) => set({ epost: v }), {
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
        {textField("Telefon", fields.telefon, (v) => set({ telefon: v }), {
          type: "tel",
          maxLength: 50,
        })}

        <p className={styles.label} style={{ margin: 0 }}>
          {accountEnd === null
            ? "Inget konto i matrikeln"
            : accountEnd
              ? `Nuvarande konto slutar på ••${accountEnd}`
              : "Det finns ett konto i matrikeln"}
        </p>
        <AccountFields
          konto={fields.konto}
          onChange={(konto) => set({ konto })}
          accountEnd={accountEnd}
        />

        {textField(
          "Gatuadress",
          fields.adress.address,
          (v) => set({ adress: { ...fields.adress, address: v } }),
          { maxLength: 200 },
        )}
        {textField(
          "Postnummer",
          fields.adress.postal_code,
          (v) => set({ adress: { ...fields.adress, postal_code: v } }),
          { inputMode: "numeric", maxLength: 10 },
        )}
        {textField(
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
