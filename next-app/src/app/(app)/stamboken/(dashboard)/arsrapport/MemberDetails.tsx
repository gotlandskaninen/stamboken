"use client";

import React from "react";
import { PublicationFields } from "@/components/member/PublicationFields";
import {
  cancelEmailCode,
  updateContact,
  verifyEmailCode,
} from "../profil/actions";
import { MbCard } from "../min-besattning/min-besattning-ui";
import { AccountFields, textField } from "./PaperChanges";
import { fmtDate, type MemberDetailsView, type PaperFields } from "./lib";
import styles from "./arsrapport.module.css";

export const NOT_MAIN =
  "Huvudmedlemmen ändrar kontaktuppgifterna, kontot för stödet och svaret om Koharen.";
const PRIVATE =
  "De här uppgifterna sparas när du skickar. Stänger du sidan behöver du fylla i dem igen.";

type Part = "adress" | "epost" | "konto" | "publicering";
const LINK_PARTS: [Part, string][] = [
  ["adress", "Ny adress eller telefon"],
  ["epost", "Ny e-postadress"],
  ["konto", "Nytt konto för stödet"],
  ["publicering", "Svar om Koharen"],
];
const SECONDARY = `sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`;

// "Dina uppgifter", last before Skicka (5.11). Logged in, the main member's own
// details are filled in and Skicka writes what changed; through the link the
// fields start empty and a change waits for the receipt mail. The state is the
// caller's, outside FormState, so it never reaches a draft or localStorage.
export function MemberDetails({
  details,
  fields,
  onChange,
  returnTo,
  track = (call) => call,
}: {
  details?: MemberDetailsView;
  fields: PaperFields;
  onChange: (f: PaperFields) => void;
  returnTo: string; // where the sign-in after an e-mail change leads
  // ReportForm's write tracking (#275): a view shown before the write is read again
  track?: <T>(call: Promise<T>) => Promise<T>;
}) {
  const [open, setOpen] = React.useState<Set<Part>>(new Set());
  // the last day to confirm a change made now (fråga 30)
  const [until] = React.useState(() =>
    new Date(Date.now() + 14 * 86_400_000).toISOString(),
  );
  if (!details || details.mode === "paper") return null;
  if (details.mode === "none")
    return (
      <MbCard title="Dina uppgifter">
        <p style={{ margin: 0 }}>{NOT_MAIN}</p>
      </MbCard>
    );
  const set = (patch: Partial<PaperFields>) =>
    onChange({ ...fields, ...patch });
  const opener = (part: Part, label: string) => (
    <button
      key={part}
      type="button"
      className={SECONDARY}
      aria-expanded={open.has(part)}
      onClick={() => setOpen(new Set(open).add(part))}
    >
      {label}
    </button>
  );
  const adress = (
    <>
      {textField(
        "Gatuadress",
        fields.adress.address,
        (v) => set({ adress: { ...fields.adress, address: v } }),
        { maxLength: 200, autoComplete: "street-address" },
      )}
      {textField(
        "Postnummer",
        fields.adress.postal_code,
        (v) => set({ adress: { ...fields.adress, postal_code: v } }),
        { inputMode: "numeric", maxLength: 10, autoComplete: "postal-code" },
      )}
      {textField(
        "Ort",
        fields.adress.city,
        (v) => set({ adress: { ...fields.adress, city: v } }),
        { maxLength: 100 },
      )}
      {textField("Telefon", fields.telefon, (v) => set({ telefon: v }), {
        type: "tel",
        maxLength: 50,
      })}
    </>
  );
  const publication = (
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
    />
  );
  const account = (
    <AccountFields konto={fields.konto} onChange={(konto) => set({ konto })} />
  );

  if (details.mode === "link") {
    return (
      <MbCard title="Har något ändrats?">
        <div className={styles.detail}>
          <p style={{ margin: 0 }}>
            Av säkerhetsskäl visar vi inte dina uppgifter här. Har inget ändrats
            behöver du inte göra något.
          </p>
          <div className={styles.choices}>
            {LINK_PARTS.filter(([part]) => !open.has(part)).map(
              ([part, label]) => opener(part, label),
            )}
          </div>
          {open.has("adress") && adress}
          {open.has("epost") &&
            textField(
              "Ny e-postadress",
              fields.epost,
              (v) => set({ epost: v }),
              {
                type: "email",
                inputMode: "email",
                maxLength: 255,
              },
            )}
          {open.has("konto") && account}
          {open.has("publicering") && (
            <>
              {publication}
              <p className={styles.note} style={{ margin: 0 }}>
                Svarar du inte ändras ingenting. Ett Nej eller färre uppgifter
                gäller direkt.
              </p>
            </>
          )}
          {open.size > 0 && (
            <p className={styles.note} style={{ margin: 0 }}>
              Gäller när du bekräftat i mejlet. Bekräfta senast {fmtDate(until)}
              . {PRIVATE}
            </p>
          )}
        </div>
      </MbCard>
    );
  }

  return (
    <MbCard title="Dina uppgifter">
      <div className={styles.detail}>
        {adress}
        <EmailChange
          email={details.contact.email}
          returnTo={returnTo}
          track={track}
        />
        <p className={styles.label} style={{ margin: 0 }}>
          {details.konto
            ? `Konto för stödet: ${details.konto}`
            : "Inget konto för stödet i matrikeln"}
        </p>
        {open.has("konto") ? account : opener("konto", "Nytt konto för stödet")}
        {publication}
        <p className={styles.note} style={{ margin: 0 }}>
          Ändrar du kontot får du ett mejl om det. {PRIVATE}
        </p>
      </div>
    </MbCard>
  );
}

// The profile's e-mail change in place (5.11): a code to the new address, then
// the change. It ends every session, so the member is asked to send first.
function EmailChange({
  email,
  returnTo,
  track,
}: {
  email: string;
  returnTo: string;
  track: <T>(call: Promise<T>) => Promise<T>;
}) {
  const [step, setStep] = React.useState<"none" | "form" | "code" | "done">(
    "none",
  );
  const [address, setAddress] = React.useState("");
  const [sentTo, setSentTo] = React.useState("");
  const [code, setCode] = React.useState("");
  const [error, setError] = React.useState("");
  const [pending, start] = React.useTransition();
  const run = (work: () => Promise<void>) => {
    setError("");
    start(work);
  };

  if (step === "done")
    return (
      <p role="status" style={{ margin: 0 }}>
        Nu är adressen bytt. Du är utloggad och får logga in igen.{" "}
        <a href={`/auth/sign-in?return_to=${encodeURIComponent(returnTo)}`}>
          Logga in
        </a>
      </p>
    );
  return (
    <div className={styles.detail}>
      <p className={styles.label} style={{ margin: 0 }}>
        E-post: {email || "ingen"}
      </p>
      {step === "none" && (
        <button
          type="button"
          className={SECONDARY}
          onClick={() => setStep("form")}
        >
          Byt e-postadress
        </button>
      )}
      {step === "form" && (
        <>
          {textField("Ny e-postadress", address, setAddress, {
            type: "email",
            inputMode: "email",
            maxLength: 255,
          })}
          <p className={styles.note} style={{ margin: 0 }}>
            Vi skickar en kod till den nya adressen. När adressen är bytt loggas
            du ut. Skicka rapporten först, så sparas det du fyllt i.
          </p>
          <div className={styles.choices}>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              disabled={pending || !address.trim()}
              onClick={() =>
                run(async () => {
                  const result = await track(
                    updateContact({ email: address.trim() }),
                  );
                  if (!result.ok) return setError(result.error);
                  if (result.emailRefused) return setError(result.emailRefused);
                  if (!result.codeSent) return setStep("none"); // the same address
                  setSentTo(address.trim());
                  setStep("code");
                })
              }
            >
              Skicka kod
            </button>
            <button
              type="button"
              className={SECONDARY}
              disabled={pending}
              onClick={() => setStep("none")}
            >
              Avbryt
            </button>
          </div>
        </>
      )}
      {step === "code" && (
        <>
          <p className={styles.note} style={{ margin: 0 }}>
            Vi har skickat en kod till <strong>{sentTo}</strong>. Skriv in den
            här. Koden gäller i tio minuter.
          </p>
          {textField("Kod", code, setCode, {
            inputMode: "numeric",
            autoComplete: "one-time-code",
            maxLength: 9,
          })}
          <div className={styles.choices}>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              disabled={pending || !code.trim()}
              onClick={() =>
                run(async () => {
                  const result = await track(verifyEmailCode(code));
                  if (result.ok) setStep("done");
                  else setError(result.error);
                })
              }
            >
              Byt adress
            </button>
            <button
              type="button"
              className={SECONDARY}
              disabled={pending}
              onClick={() =>
                run(async () => {
                  const result = await track(cancelEmailCode());
                  if (!result.ok) return setError(result.error);
                  setCode("");
                  setStep("none");
                })
              }
            >
              Avbryt
            </button>
          </div>
        </>
      )}
      {error && (
        <p className={styles.errorText} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
