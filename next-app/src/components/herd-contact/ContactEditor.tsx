"use client";

import React from "react";
import {
  CONFLICT_TEXT,
  FIELD_LABEL,
  isConflict,
  isFetched,
  isReader,
  joinAddress,
  privacyOf,
  roleLabel,
  shownRow,
  shownTop,
  splitAddress,
  type Contact,
  type ContactField,
  type HerdFields,
  type OnSave,
  type OwnerContact,
  type Privacy,
  type ReaderContact,
} from "./contactTypes";
import PrivacyChips from "./PrivacyChips";
import styles from "./herd-contact.module.css";

const FIELDS: ContactField[] = [
  "name",
  "email",
  "mobile_phone",
  "physical_address",
];
const CHIP_LABEL: Record<ContactField, string> = {
  name: "Vem ser namnet",
  email: "Vem ser e-posten",
  mobile_phone: "Vem ser mobilen",
  physical_address: "Vem ser adressen",
};
const REGISTER_NOTE: Record<ContactField, string> = {
  name: "",
  email: "från personens profil",
  mobile_phone: "från personens profil",
  physical_address: "hushållets adress",
};

interface RowState {
  source: "egen" | "medlemskap";
  text: string;
  street: string;
  postal: string;
  city: string;
  privacy: Privacy;
}
interface Form {
  sel: string; // person id, "annan" or ""
  annan: string;
  rows: Partial<Record<ContactField, RowState>>;
}

/** a read-only value on one line: the address's parts joined with commas */
const oneLine = (f: ContactField, v: string | null | undefined) =>
  f === "physical_address" && v ? v.split("|").filter(Boolean).join(", ") : v;

function initForm(herd: HerdFields, contact: Contact): Form {
  const rows: Form["rows"] = {};
  const build = (
    f: ContactField,
    source: RowState["source"],
    privacy: Privacy,
  ) => {
    const text = herd[f] ?? "";
    rows[f] = {
      source,
      text,
      ...splitAddress(f === "physical_address" ? text : ""),
      privacy,
    };
  };
  if (isReader(contact)) {
    for (const f of FIELDS) {
      const r = contact.rows[f];
      build(
        f,
        isFetched(r.source) ? "medlemskap" : "egen",
        privacyOf(r.privacy),
      );
    }
    const sel =
      contact.mode === "person"
        ? String(contact.contact_member?.id ?? "")
        : contact.mode === "fritext"
          ? "annan"
          : "";
    return {
      sel,
      annan: contact.mode === "fritext" ? (herd.name ?? "") : "",
      rows,
    };
  }
  for (const f of FIELDS) {
    const r = contact.rows[f];
    if (r?.source === "egen") build(f, "egen", privacyOf(r.privacy));
  }
  return { sel: "", annan: "", rows };
}

export default function ContactEditor({
  herd: herdProp,
  contact: contactProp,
  onSave,
  onReload,
  onDone,
  onCancel,
}: {
  herd: HerdFields;
  contact: Contact;
  onSave: OnSave;
  /** the form was out of date (409): fetch the herd again */
  onReload?: () => void;
  onDone?: () => void;
  onCancel?: () => void;
}) {
  // The draft and the state it was made from (`base`, which the server checks against) stay while
  // the editor is open; a new herd object from a save elsewhere on the page does not reset them.
  const [base, setBase] = React.useState({
    herd: herdProp,
    contact: contactProp,
    init: initForm(herdProp, contactProp),
  });
  const { herd, contact, init } = base;
  const reader = isReader(contact);
  const compared = reader && contact.mode !== "ej_jamford";
  const chooses = reader && !!contact.persons;
  const [form, setForm] = React.useState(init);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  // After a save or a 409 the next data to arrive replaces the draft: `after` holds the props at that moment.
  const [after, setAfter] = React.useState<{
    herd: HerdFields;
    contact: Contact;
  } | null>(null);
  const latest = React.useRef({ herd: herdProp, contact: contactProp });
  React.useEffect(() => {
    latest.current = { herd: herdProp, contact: contactProp };
  });
  // data that grants less than the draft was made from must not keep showing the old values
  const narrows =
    isReader(contact) &&
    (!isReader(contactProp) || (!!contact.persons && !contactProp.persons));
  // a non-reader's own row that is now fetched or gone: only that row's old value and draft go
  const gone =
    isReader(contact) || isReader(contactProp)
      ? []
      : (Object.keys(contact.rows) as ContactField[]).filter(
          (f) =>
            contact.rows[f]?.source === "egen" &&
            contactProp.rows[f]?.source !== "egen",
        );
  if (
    (herdProp !== herd || contactProp !== contact) &&
    ((after && (herdProp !== after.herd || contactProp !== after.contact)) ||
      herdProp?.herd !== herd?.herd ||
      narrows)
  ) {
    setAfter(null);
    const fresh = initForm(herdProp, contactProp);
    setBase({ herd: herdProp, contact: contactProp, init: fresh });
    setForm(fresh);
  } else if (gone.length) {
    const drop = <T,>(rows: Partial<Record<ContactField, T>>) => {
      const kept = { ...rows };
      for (const f of gone) delete kept[f];
      return kept;
    };
    const rows = { ...(contact as OwnerContact).rows };
    for (const f of gone) rows[f] = (contactProp as OwnerContact).rows[f]; // fetched, or gone
    // the other rows keep their draft and the state it was made from, so a change there still gives 409
    setBase({
      herd,
      contact: { rows },
      init: { ...init, rows: drop(init.rows) },
    });
    setForm((s) => ({ ...s, rows: drop(s.rows) }));
  }

  const annan = form.sel === "annan";
  const personChanged = form.sel !== init.sel;
  const setRow = (f: ContactField, patch: Partial<RowState>) =>
    setForm((s) => ({
      ...s,
      rows: { ...s.rows, [f]: { ...s.rows[f]!, ...patch } },
    }));

  function pick(sel: string) {
    setForm((s) => {
      const rows = { ...s.rows };
      if (sel === "annan") {
        // a contact outside the register has no person to fetch e-post and mobil from
        for (const f of ["email", "mobile_phone"] as const) {
          const r = rows[f];
          if (r && r.source !== "egen")
            rows[f] = { ...r, source: "egen", text: "" };
        }
      }
      return { ...s, sel, rows };
    });
  }

  const locked = (f: ContactField) =>
    annan && (f === "email" || f === "mobile_phone");
  const value = (f: ContactField, r: RowState) =>
    f === "physical_address" ? joinAddress(r.street, r.postal, r.city) : r.text;
  const dirty = (f: ContactField, r: RowState, i: RowState) =>
    r.source !== i.source ||
    r.privacy !== i.privacy ||
    (r.source === "egen" &&
      (f === "physical_address"
        ? r.street !== i.street || r.postal !== i.postal || r.city !== i.city
        : r.text !== i.text));

  function build(): { patch?: Record<string, unknown>; error?: string } {
    const rows: Record<string, unknown> = {};
    // against the form's first value: a stored name with a trailing space that nobody touched is not a change
    const nameEdited = annan && form.annan !== init.annan;
    for (const f of FIELDS) {
      const r = form.rows[f];
      const i = init.rows[f];
      if (!r || !i || !dirty(f, r, i)) continue;
      const own = r.source === "egen";
      if (f === "name" && compared) {
        // the contact person's privacy; a changed person resets it on the server
        if (r.privacy === i.privacy) continue;
        const shown = shownRow(
          "name",
          (contact as ReaderContact).rows.name,
          herd,
        );
        if (annan) {
          // a fritext name edit is an own-row edit: the new name and the chosen privacy go together;
          // without an edit `value` is left out, so the stored name stays as it is
          if (form.annan.trim())
            rows.name = {
              source: "egen",
              ...(nameEdited ? { value: form.annan.trim() } : {}),
              privacy: r.privacy,
              shown,
            };
        } else if (!personChanged || i.source === "medlemskap") {
          // also on a change between persons: the server applies decision 14 to the chosen privacy
          // (from fritext to a person the row would name the main member, so it is left out)
          rows.name = {
            source: r.source,
            ...(own ? {} : { value: null }),
            privacy: r.privacy,
            shown,
          };
        } else {
          // from fritext to a person the name row would name the main member, and without it the server
          // decides the name's privacy (decision 14): one PATCH cannot carry the change and a chosen privacy
          return {
            error:
              "Spara bytet av kontaktperson först. Ändra sedan vem som ser namnet.",
          };
        }
        continue;
      }
      const blank =
        f === "physical_address"
          ? !(r.street.trim() || r.postal.trim() || r.city.trim())
          : !r.text.trim();
      const sent =
        !own || blank
          ? null
          : f === "physical_address" &&
              r.street === i.street &&
              r.postal === i.postal &&
              r.city === i.city
            ? i.text // untouched address: exactly as stored, never only the part before the first "|"
            : value(f, r).trim();
      // an explicit clear (null) goes to the server, which decides; only the register-bound form cannot express it
      if (
        own &&
        blank &&
        compared &&
        !locked(f) &&
        // an explicit clear is for a row that was own and has no register value; a fetched row switched to Egen needs a value
        !(
          i.source === "egen" &&
          (contact as ReaderContact).rows[f].alternative == null
        )
      ) {
        return {
          error: `Skriv ${FIELD_LABEL[f].toLowerCase()} eller välj Från medlemskapet.`,
        };
      }
      // a privacy-only change of an own row sends no value: null would clear it on the server
      const valueSame =
        own &&
        i.source === "egen" &&
        (f === "physical_address"
          ? r.street === i.street && r.postal === i.postal && r.city === i.city
          : r.text === i.text);
      rows[f] = {
        source: r.source,
        ...(valueSame ? {} : { value: sent }),
        privacy: r.privacy,
        shown: reader
          ? shownRow(f, (contact as ReaderContact).rows[f], herd)
          : { source: "egen", value: herd[f] ?? null, privacy: i.privacy },
      };
    }
    const top: Record<string, unknown> = {};
    let topChanged = false;
    if (compared) {
      const c = contact as ReaderContact;
      top.shown = shownTop(c, herd);
      if (chooses) {
        if (annan && !form.annan.trim())
          return { error: "Skriv kontaktens namn." };
        topChanged = personChanged || nameEdited;
        if (topChanged) {
          top.contact_member = annan || !form.sel ? null : Number(form.sel);
          top.name = annan ? form.annan.trim() : null;
        }
      }
    }
    if (!topChanged && Object.keys(rows).length === 0) return {};
    return { patch: { contact: { ...top, rows } } };
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const { patch, error: invalid } = build();
    if (invalid) return setError(invalid);
    if (!patch) return setError("Inga ändringar att spara.");
    setBusy(true);
    try {
      const res = await onSave(patch as { contact: Record<string, unknown> });
      if (res.success) {
        setAfter(latest.current);
        onDone?.();
      } else if (isConflict(res)) {
        setAfter(latest.current);
        setError(CONFLICT_TEXT);
        onReload?.();
      } else setError(res.error);
    } catch {
      setError("Kunde inte spara. Försök igen.");
    } finally {
      setBusy(false);
    }
  }

  const fields = FIELDS.filter(
    (f) =>
      !(compared && f === "name") &&
      (form.rows[f] || (!reader && contact.rows[f])),
  );
  const c = reader ? (contact as ReaderContact) : null;

  return (
    <form className={styles.edit} onSubmit={submit} noValidate>
      {compared && c && (
        <div>
          {chooses ? (
            <>
              <label className={styles.label} htmlFor="contact-person">
                Kontaktperson
              </label>
              <select
                id="contact-person"
                className="sb-input"
                value={form.sel}
                onChange={(e) => pick(e.target.value)}
              >
                {init.sel === "" && (
                  <option value="">Välj kontaktperson</option>
                )}
                {c.persons!.map((p) => (
                  <option key={p.id} value={String(p.id)}>
                    {p.name}, {roleLabel(p.role)}
                  </option>
                ))}
                <option value="annan">
                  Annan kontakt, som inte finns i matrikeln
                </option>
              </select>
              <p className={styles.hint}>
                {annan
                  ? "En kontakt utanför matrikeln har egna uppgifter för e-post och mobil."
                  : "Namn, e-post och mobil hämtas från personen."}
              </p>
              {annan && (
                <div style={{ marginTop: 8 }}>
                  <label className={styles.label} htmlFor="contact-annan">
                    Namn
                  </label>
                  <input
                    id="contact-annan"
                    className="sb-input"
                    placeholder="För- och efternamn"
                    value={form.annan}
                    onChange={(e) =>
                      setForm((s) => ({ ...s, annan: e.target.value }))
                    }
                  />
                </div>
              )}
            </>
          ) : (
            <p className={styles.hint}>
              Kontaktperson:{" "}
              {c.contact_member?.name ?? herd.name ?? "ingen vald"}. Bara
              huvudmedlemmen, genbanksansvarig och admin byter kontaktperson.
            </p>
          )}
          {form.rows.name && (
            <PrivacyChips
              label={CHIP_LABEL.name}
              value={form.rows.name.privacy}
              onChange={(privacy) => setRow("name", { privacy })}
            />
          )}
        </div>
      )}

      {fields.map((f) => {
        const r = form.rows[f];
        const i = init.rows[f];
        if (!r || !i) {
          // a non-reader's fetched row: the current read's value when its visibility lets the user see it
          // (not `herd`, which can be older data, with a value that was own then)
          const live =
            !isReader(contactProp) && contactProp.rows[f]?.source === "hamtad"
              ? oneLine(f, herdProp[f] ?? null)
              : null;
          return (
            <div key={f}>
              <span className={styles.label}>{FIELD_LABEL[f]}</span>
              <div className={styles.readonly}>
                {live ? (
                  <>
                    <span>{live}</span>
                    <small>Hämtas från medlemskapet</small>
                  </>
                ) : (
                  "Hämtas från medlemskapet"
                )}
              </div>
            </div>
          );
        }
        const labelId = `contact-l-${f}`;
        const row = c?.rows[f];
        // a switch to the register needs a register value: a fetched row, or an own row that differs from it
        const switchable =
          compared && (i.source === "medlemskap" || row?.alternative != null);
        const personUnknown =
          personChanged &&
          !annan &&
          (f === "email" || f === "mobile_phone") &&
          i.source === "medlemskap";
        const registerValue = personUnknown
          ? null
          : i.source === "medlemskap"
            ? i.text
            : row?.alternative;
        const registerShown = oneLine(f, registerValue);
        return (
          <div key={f}>
            <span className={styles.label} id={labelId}>
              {FIELD_LABEL[f]}
            </span>
            {switchable && (
              <div
                className={styles.seg}
                role="group"
                aria-labelledby={labelId}
              >
                <button
                  type="button"
                  aria-pressed={r.source === "medlemskap"}
                  disabled={locked(f)}
                  onClick={() =>
                    r.source !== "medlemskap" &&
                    setRow(f, { source: "medlemskap" })
                  }
                >
                  Från medlemskapet
                </button>
                <button
                  type="button"
                  aria-pressed={r.source === "egen"}
                  onClick={() =>
                    r.source !== "egen" && setRow(f, { source: "egen" })
                  }
                >
                  Egen
                </button>
              </div>
            )}
            {r.source === "medlemskap" ? (
              <div className={styles.readonly}>
                <span>
                  {registerShown ??
                    `Hämtas från ${form.sel ? "vald person" : "medlemskapet"}`}
                </span>
                <small>{REGISTER_NOTE[f]}</small>
              </div>
            ) : f === "physical_address" ? (
              <div className={styles.addr}>
                <input
                  className="sb-input"
                  aria-label="Gatuadress"
                  placeholder="Gatuadress"
                  value={r.street}
                  onChange={(e) => setRow(f, { street: e.target.value })}
                />
                <input
                  className="sb-input"
                  aria-label="Postnummer"
                  placeholder="Postnummer"
                  inputMode="numeric"
                  value={r.postal}
                  onChange={(e) => setRow(f, { postal: e.target.value })}
                />
                <input
                  className="sb-input"
                  aria-label="Ort"
                  placeholder="Ort"
                  value={r.city}
                  onChange={(e) => setRow(f, { city: e.target.value })}
                />
              </div>
            ) : (
              <input
                className="sb-input"
                aria-labelledby={labelId}
                value={r.text}
                onChange={(e) => setRow(f, { text: e.target.value })}
              />
            )}
            <PrivacyChips
              label={CHIP_LABEL[f]}
              value={r.privacy}
              onChange={(privacy) => setRow(f, { privacy })}
            />
          </div>
        );
      })}

      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
      <div className={styles.actions}>
        {onCancel && (
          <button
            type="button"
            className="sb-btn sb-btn-ghost sb-btn-sm"
            onClick={onCancel}
            disabled={busy}
          >
            Avbryt
          </button>
        )}
        <button type="submit" className="sb-btn sb-btn-sm" disabled={busy}>
          {busy ? "Sparar…" : "Spara"}
        </button>
      </div>
    </form>
  );
}
