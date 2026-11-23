"use client";

import React from "react";
import Link from "next/link";
import {
  askText,
  CONFLICT_TEXT,
  FIELD_LABEL,
  firstName,
  formatAddress,
  isConflict,
  isFetched,
  isReader,
  roleLabel,
  shownRow,
  shownTop,
  type Contact,
  type ContactField,
  type HerdFields,
  type OnSave,
  type ReaderContact,
} from "./contactTypes";
import PrivacyBadge from "./PrivacyBadge";
import styles from "./herd-contact.module.css";

const ROWS: ContactField[] = ["email", "mobile_phone", "physical_address"];

interface Line {
  field: ContactField;
  value: string | null;
  fetched: boolean;
  privacy?: string;
  /** a non-reader's fetched row: no value shown */
  hidden?: boolean;
}

function lines(contact: Contact, herd: HerdFields): Line[] {
  const fields: ContactField[] =
    isReader(contact) && contact.mode !== "ej_jamford"
      ? ROWS
      : (["name", ...ROWS] as ContactField[]);
  return fields.flatMap((field): Line[] => {
    if (isReader(contact)) {
      const r = contact.rows[field];
      return [
        {
          field,
          value: herd[field] ?? null,
          fetched: isFetched(r.source),
          privacy: r.privacy,
        },
      ];
    }
    const r = contact.rows[field];
    if (!r) return [];
    return r.source === "hamtad"
      ? [{ field, value: null, fetched: true, hidden: true }]
      : [{ field, value: r.value, fetched: false, privacy: r.privacy }];
  });
}

function Value({ line }: { line: Line }) {
  if (line.hidden)
    return <span className={styles.muted}>Hämtas från medlemskapet</span>;
  if (!line.value) return <span className={styles.muted}>Saknas</span>;
  if (line.field === "email")
    return (
      <a className={`sb-link ${styles.value}`} href={`mailto:${line.value}`}>
        {line.value}
      </a>
    );
  if (line.field === "physical_address") {
    const [street, place] = formatAddress(line.value);
    return (
      <span className={styles.value}>
        {street}
        {place && (
          <>
            <br />
            {place}
          </>
        )}
      </span>
    );
  }
  return <span className={styles.value}>{line.value}</span>;
}

function AskBox({
  field,
  alternative,
  onAnswer,
  busy,
}: {
  field: ContactField;
  alternative: string | null;
  onAnswer: (f: ContactField, a: "behall" | "anvand") => void;
  busy: boolean;
}) {
  const [Noun, noun] = askText(field);
  return (
    <div
      className={styles.ask}
      role="group"
      aria-label={`${Noun} ${alternative ? "skiljer sig" : "behöver ett svar"}`}
    >
      {alternative ? (
        <p>
          {Noun} skiljer sig från ditt medlemskap, där det står{" "}
          <span className={styles.alt}>{alternative}</span>. Stämmer {noun} för
          besättningen?
        </p>
      ) : (
        <p>Stämmer det? {Noun} kan inte jämföras med medlemskapet.</p>
      )}
      <div className={styles.btns}>
        <button
          type="button"
          className="sb-btn sb-btn-secondary sb-btn-sm"
          disabled={busy}
          onClick={() => onAnswer(field, "behall")}
        >
          Ja, behåll
        </button>
        {alternative && (
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            disabled={busy}
            onClick={() => onAnswer(field, "anvand")}
          >
            Använd medlemskapets
          </button>
        )}
      </div>
    </div>
  );
}

function Rows({
  items,
  contact,
  herd,
  onAnswer,
  busy,
}: {
  items: Line[];
  contact: Contact;
  herd: HerdFields;
  onAnswer?: (f: ContactField, a: "behall" | "anvand") => void;
  busy: boolean;
}) {
  return (
    <dl className={styles.rows}>
      {items.map((l) => {
        const row = isReader(contact) ? contact.rows[l.field] : null;
        const ask = row && row.pending && row.alternative && onAnswer;
        return (
          <div key={l.field} className={styles.row}>
            <dt>{FIELD_LABEL[l.field]}</dt>
            <dd>
              <Value line={l} />
              {l.privacy && (
                <span className={styles.metaLine}>
                  <PrivacyBadge level={l.privacy} />
                </span>
              )}
              {ask && row && (
                <AskBox
                  field={l.field}
                  alternative={row.alternative!}
                  onAnswer={onAnswer}
                  busy={busy}
                />
              )}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export default function ContactView({
  herd,
  contact,
  onSave,
  onReload,
  locked,
}: {
  herd: HerdFields;
  contact: Contact;
  onSave?: OnSave;
  onReload?: () => void;
  /** another save on the page is running: the answer buttons wait */
  locked?: boolean;
}) {
  const [ownBusy, setBusy] = React.useState(false);
  const busy = ownBusy || !!locked;
  const [message, setMessage] = React.useState<string | null>(null);
  const reader = isReader(contact);
  const person = reader ? (contact as ReaderContact).contact_member : null;
  const all = lines(contact, herd);
  const nameRow =
    reader && (contact as ReaderContact).mode !== "ej_jamford"
      ? (contact as ReaderContact).rows.name
      : null;
  const fromRegister = all.filter((l) => l.fetched);
  const own = all.filter((l) => !l.fetched && l.value);
  const grouped = fromRegister.length > 0;

  // ruling 16: only the active huvudmedlem is named as the one who changes her own details (#139 is open)
  const main = person?.role === "huvudmedlem" ? firstName(person.name) : null;

  async function answer(field: ContactField, a: "behall" | "anvand") {
    if (!reader || !onSave) return;
    const c = contact as ReaderContact;
    const shown = shownRow(field, c.rows[field], herd);
    setBusy(true);
    setMessage(null);
    const res = await onSave({
      contact: {
        shown: shownTop(c, herd),
        rows: {
          [field]:
            a === "behall"
              ? { source: "egen", privacy: shown.privacy, answer: a, shown }
              : { source: "medlemskap", value: null, answer: a, shown },
        },
      },
    });
    setBusy(false);
    if (res.success) {
      setMessage(
        a === "behall"
          ? "Sparat: uppgiften är egen för besättningen."
          : "Sparat: uppgiften hämtas nu från ditt medlemskap. Synligheten är Endast genbanksansvarig.",
      );
    } else if (isConflict(res)) {
      setMessage(CONFLICT_TEXT);
      onReload?.();
    } else {
      setMessage(res.error);
    }
  }

  const rowsProps = {
    contact,
    herd,
    onAnswer: reader && onSave ? answer : undefined,
    busy,
  };

  return (
    <div>
      {reader && (contact as ReaderContact).mode !== "ej_jamford" && (
        <>
          <div className={styles.person}>
            <span className={styles.avatar} aria-hidden="true">
              {(person?.name ?? herd.name ?? "?")
                .split(" ")
                .map((p: string) => p[0])
                .slice(0, 2)
                .join("")}
            </span>
            <div>
              <div className={styles.personName}>
                {person?.name ?? herd.name ?? "Ingen kontaktperson vald"}
              </div>
              <div className={styles.personRole}>
                {person
                  ? `Kontaktperson · ${roleLabel(person.role)}`
                  : "Kontaktperson · utanför matrikeln"}
              </div>
            </div>
          </div>
          {nameRow && (
            <div className={styles.metaLine} style={{ paddingBottom: 12 }}>
              <PrivacyBadge level={nameRow.privacy} />
            </div>
          )}
          {nameRow?.pending && onSave && (
            <AskBox
              field="name"
              alternative={nameRow.alternative}
              onAnswer={answer}
              busy={busy}
            />
          )}
        </>
      )}
      {grouped && (
        <>
          <h3 className={styles.groupTitle}>
            <span className={styles.src}>Från ditt medlemskap</span>
            <small>rättas en gång, gäller överallt</small>
          </h3>
          <Rows items={fromRegister} {...rowsProps} />
        </>
      )}
      {own.length > 0 && (
        <>
          {grouped && (
            <h3 className={styles.groupTitle}>
              <span className={`${styles.src} ${styles.srcOwn}`}>
                Egna för besättningen
              </span>
              <small>gäller bara här</small>
            </h3>
          )}
          <Rows items={own} {...rowsProps} />
        </>
      )}
      {all.every((l) => !l.value && !l.hidden) && (
        <p className="sb-meta" style={{ margin: 0 }}>
          Ingen kontakt angiven ännu. Tryck Redigera.
        </p>
      )}
      {message && (
        <p className={styles.hint} role="status">
          {message}
        </p>
      )}
      {grouped && (
        <p className={styles.foot}>
          {main ? (
            <>
              E-post och mobil från medlemskapet ändrar {main} själv under{" "}
              <Link className="sb-link" href="/stamboken/profil">
                Profil → Kontakt
              </Link>
              .
            </>
          ) : (
            <>E-post och mobil från medlemskapet rättar matrikeladmin.</>
          )}{" "}
          Adressen gäller hela hushållet och ändras av huvudmedlemmen.
        </p>
      )}
    </div>
  );
}
