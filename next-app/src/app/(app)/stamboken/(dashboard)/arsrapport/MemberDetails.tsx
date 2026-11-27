"use client";

import React from "react";
import { formatPostalCode, isValidPostalCode } from "@/lib/postal";
import type { Mode } from "@/lib/mode";
import {
  PublicationFields,
  toConsent,
  type Publication,
} from "@/components/member/PublicationFields";
import {
  cancelEmailCode,
  updateContact,
  updateConsent,
  verifyEmailCode,
} from "../profil/actions";
import { MbCard } from "../min-besattning/min-besattning-ui";
import { AccountFields, TextField, textField } from "./PaperChanges";
import { saveAccount } from "./actions";
import {
  CONSENT_TEXT_VERSION,
  detailsBody,
  detailsFields,
  emptyPaperFields,
  fmtDate,
  type Matrikel,
  type MemberDetailsView,
  type PaperFields,
} from "./lib";
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

type Track = <T>(call: Promise<T>) => Promise<T>;
type Main = Extract<MemberDetailsView, { mode: "main" }>;
export type RemainingDetails = () => Promise<Matrikel | null>;

// Private input is kept outside FormState, so it never reaches a draft or localStorage.
export function MemberDetails({
  details,
  fields,
  onChange,
  herd,
  year,
  env,
  remaining,
  track = (call) => call,
}: {
  details?: MemberDetailsView;
  fields: PaperFields;
  onChange: (f: PaperFields) => void;
  herd: string;
  year: number;
  env: Mode;
  remaining?: React.Ref<RemainingDetails>;
  track?: Track;
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
          {open.has("adress") &&
            CONTACT_FIELDS.map(([key, label, attrs]) => (
              <React.Fragment key={key}>
                {textField(
                  label,
                  contactValue(fields, key),
                  (v) => onChange(editContact(fields, key, v)),
                  attrs,
                )}
              </React.Fragment>
            ))}
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
    <MainDetails
      details={details}
      herd={herd}
      year={year}
      env={env}
      remaining={remaining}
      track={track}
    />
  );
}

type ContactKey = "address" | "postal_code" | "city" | "phone";
const CONTACT_FIELDS: [
  ContactKey,
  string,
  React.InputHTMLAttributes<HTMLInputElement>,
][] = [
  ["address", "Gatuadress", { maxLength: 200, autoComplete: "street-address" }],
  [
    "postal_code",
    "Postnummer",
    { inputMode: "numeric", maxLength: 10, autoComplete: "postal-code" },
  ],
  ["city", "Ort", { maxLength: 100 }],
  ["phone", "Telefon", { type: "tel", maxLength: 50 }],
];
const contactValue = (f: PaperFields, k: ContactKey) =>
  k === "phone" ? f.telefon : f.adress[k];
const editContact = (f: PaperFields, k: ContactKey, v: string) =>
  k === "phone"
    ? { ...f, telefon: v }
    : { ...f, adress: { ...f.adress, [k]: v } };

// As in the report's _contact: spaces, dots and hyphens are separators.
function completeAccount(k: PaperFields["konto"]) {
  const clearing = k.clearing.replace(/[\s.-]/g, "");
  const number = k.konto.replace(/[\s.-]/g, "");
  if (k.typ === "plusgiro") return !clearing && /^\d{2,8}$/.test(number);
  if (k.typ === "bankgiro") return !clearing && /^\d{7,8}$/.test(number);
  return /^\d{4,5}$/.test(clearing) && /^\d{5,12}$/.test(number);
}

function MainDetails({
  details,
  herd,
  year,
  env,
  remaining,
  track,
}: {
  details: Main;
  herd: string;
  year: number;
  env: Mode;
  remaining?: React.Ref<RemainingDetails>;
  track: Track;
}) {
  const saved = React.useRef(details);
  const [fields, setFields] = React.useState(() => detailsFields(details));
  const current = React.useRef(fields);
  const edit = (next: PaperFields) => {
    current.current = next;
    setFields(next);
  };
  const [account, setAccount] = React.useState(details.konto);
  const [open, setOpen] = React.useState(false);
  const writes = React.useRef(new Map<string, Promise<void>>());
  type Feedback = { text: string; state: "saved" | "saving" | "error" };
  const [messages, setMessages] = React.useState<Record<string, Feedback>>({});
  const message = (
    key: string,
    text: string,
    state: Feedback["state"] = "saved",
  ) => setMessages((previous) => ({ ...previous, [key]: { text, state } }));
  const feedback = (key: string) =>
    messages[key]?.text && (
      <span
        id={`report-detail-${key}`}
        className={
          messages[key].state === "error" ? styles.errorText : styles.note
        }
        role={messages[key].state === "error" ? "alert" : "status"}
      >
        {messages[key].text}
      </span>
    );
  const busy = (key: string) => messages[key]?.state === "saving";
  const save = (key: string, work: () => Promise<void>) => {
    if (writes.current.has(key)) return;
    message(key, "Sparar…", "saving");
    const call = work()
      .catch(() =>
        message(key, "Det gick inte att nå servern. Försök igen.", "error"),
      )
      .finally(() => writes.current.delete(key));
    writes.current.set(key, track(call));
  };
  // A click on Skicka can itself blur a field. Diff only after its write has answered.
  React.useImperativeHandle(remaining, () => async () => {
    await Promise.all(writes.current.values());
    return detailsBody(saved.current, current.current);
  });
  const blur = (key: ContactKey) => {
    const raw = contactValue(current.current, key);
    const value = key === "postal_code" ? formatPostalCode(raw) : raw.trim();
    if (value !== raw) edit(editContact(current.current, key, value));
    if (value === saved.current.contact[key].trim()) return;
    if (key === "postal_code" && !isValidPostalCode(value))
      return message(key, "Postnummer ska vara fem siffror", "error");
    save(key, async () => {
      const result = await updateContact({ [key]: value }, env);
      if (!result.ok) return message(key, result.error, "error");
      saved.current = {
        ...saved.current,
        contact: { ...saved.current.contact, [key]: value },
      };
      message(key, "Kontaktuppgifter sparade");
    });
  };
  const publish = (answer: Publication | null) => {
    if (!answer) return;
    edit({
      ...current.current,
      consent: answer.ja ? "ja" : "nej",
      utom: answer.utom,
    });
    save("publicering", async () => {
      const result = await updateConsent(
        {
          ...toConsent(answer),
          version: saved.current.publicering_version,
          text_version: CONSENT_TEXT_VERSION,
        },
        env,
      );
      if (!result.ok) return message("publicering", result.error, "error");
      if (result.version === undefined)
        return message(
          "publicering",
          "Ladda om sidan och kontrollera svaret.",
          "error",
        );
      saved.current = {
        ...saved.current,
        publicering: answer,
        publicering_version: result.version,
      };
      message("publicering", "Publiceringsval sparade");
    });
  };
  const storeAccount = () =>
    save("konto", async () => {
      const konto = detailsBody(saved.current, current.current)?.konto;
      if (!konto) return;
      const result = await saveAccount(herd, year, konto, env);
      if (!result.ok) return message("konto", result.problem.detail, "error");
      edit({ ...current.current, konto: emptyPaperFields().konto });
      setAccount(result.data.konto);
      setOpen(false);
      message("konto", "Sparat i matrikeln: konto.");
    });
  return (
    <MbCard title="Dina uppgifter">
      <div className={styles.detail}>
        <p className={styles.note} style={{ margin: 0 }}>
          Ändringarna sparas direkt, även om du inte skickar årsrapporten.
        </p>
        {CONTACT_FIELDS.map(([key, label, attrs]) => (
          <React.Fragment key={key}>
            <TextField
              label={label}
              {...attrs}
              value={contactValue(fields, key)}
              onChange={(e) => {
                edit(editContact(current.current, key, e.target.value));
                message(key, "");
              }}
              disabled={busy(key)}
              onBlur={() => blur(key)}
              aria-describedby={
                messages[key]?.text ? `report-detail-${key}` : undefined
              }
              aria-invalid={messages[key]?.state === "error" || undefined}
            />
            {feedback(key)}
          </React.Fragment>
        ))}
        <EmailChange
          email={details.contact.email}
          returnTo={`/stamboken/arsrapport/${herd}/${year}`}
          track={track}
          env={env}
        />
        <p className={styles.label} style={{ margin: 0 }}>
          {account
            ? `Konto för stödet: ${account}`
            : "Inget konto för stödet i matrikeln"}
        </p>
        {open ? (
          <fieldset disabled={busy("konto")} className={styles.detail}>
            <AccountFields
              konto={fields.konto}
              onChange={(konto) => {
                edit({ ...current.current, konto });
                message("konto", "");
              }}
            />
            <button
              type="button"
              className={SECONDARY}
              disabled={!completeAccount(fields.konto)}
              onClick={storeAccount}
            >
              Spara kontot
            </button>
          </fieldset>
        ) : (
          <button
            type="button"
            className={SECONDARY}
            onClick={() => setOpen(true)}
          >
            Nytt konto för stödet
          </button>
        )}
        {feedback("konto")}
        <p className={styles.note} style={{ margin: 0 }}>
          Ändrar du kontot får du ett mejl om det.
        </p>
        <PublicationFields
          value={
            fields.consent
              ? { ja: fields.consent === "ja", utom: fields.utom }
              : null
          }
          onChange={publish}
          disabled={busy("publicering")}
        />
        {feedback("publicering")}
      </div>
    </MbCard>
  );
}

// The profile's e-mail change in place (5.11): a code to the new address, then
// the change. It ends every session, so the member is asked to send first.
function EmailChange({
  email,
  env,
  returnTo,
  track,
}: {
  email: string;
  env: Mode;
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
  const close = () => {
    setAddress("");
    setError("");
    setStep("none");
  };
  const run = (work: () => Promise<void>) => {
    setError("");
    start(async () => {
      try {
        await work();
      } catch {
        setError("Det gick inte att nå servern. Försök igen.");
      }
    });
  };

  const requesting = React.useRef(false);
  const requestCode = () => {
    const next = address.trim();
    if (!next || pending || requesting.current) return;
    if (next.toLowerCase() === email.trim().toLowerCase()) return close();
    requesting.current = true;
    run(async () => {
      try {
        const result = await track(updateContact({ email: next }, env));
        if (!result.ok) return setError(result.error);
        if (result.emailRefused) return setError(result.emailRefused);
        if (!result.codeSent) return close();
        setSentTo(next);
        setStep("code");
      } finally {
        requesting.current = false;
      }
    });
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
          <TextField
            label="Ny e-postadress"
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            disabled={pending}
            type="email"
            inputMode="email"
            maxLength={255}
          />
          <p className={styles.note} style={{ margin: 0 }}>
            Vi skickar en kod till den nya adressen. När adressen är bytt loggas
            du ut. Skicka rapporten först, så sparas det du fyllt i.
          </p>
          <div className={styles.choices}>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              disabled={pending || !address.trim()}
              onClick={requestCode}
            >
              Skicka kod
            </button>
            <button
              type="button"
              className={SECONDARY}
              disabled={pending}
              onClick={close}
            >
              Avbryt
            </button>
          </div>
        </>
      )}
      {step === "code" && (
        <>
          <p className={styles.note} style={{ margin: 0 }} role="status">
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
                  const result = await track(verifyEmailCode(code, env));
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
                  const result = await track(cancelEmailCode(env));
                  if (!result.ok) return setError(result.error);
                  setCode("");
                  close();
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
