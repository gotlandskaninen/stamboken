"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormControlLabel, Switch } from "@mui/material";
import ds from "@/styles/ds-admin.module.css";
import ContactView from "@/components/herd-contact/ContactView";
import ContactEditor from "@/components/herd-contact/ContactEditor";
import {
  CONFLICT_TEXT,
  isReader,
  type OnSave,
} from "@/components/herd-contact/contactTypes";
import styles from "../../admin.module.css";
import { saveHerdContact, updateHerd, type UpdateHerdFields } from "../actions";
import type { HerdDetail } from "./page";

const fields = (herd: HerdDetail) => ({
  wire_phone: herd.wire_phone ?? "",
  www: herd.www ?? "",
  is_active: herd.is_active,
});

export function HerdEditClient({ herd }: { herd: HerdDetail }) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [start, setStart] = useState(() => fields(herd));
  const [form, setForm] = useState(start);
  // After a 409 the next herd to arrive replaces the form: `after` is the herd at that moment.
  const [after, setAfter] = useState<HerdDetail | null>(null);
  const latest = useRef(herd);
  useEffect(() => {
    latest.current = herd;
  });
  if (after && herd !== after) {
    setAfter(null);
    const fresh = fields(herd);
    setStart(fresh);
    setForm(fresh);
  }
  const contact = herd.contact;
  // no contact person: mode ingen, or a compared herd whose membership has no active person left
  const missing =
    isReader(contact) &&
    (contact.mode === "ingen" ||
      (contact.mode !== "ej_jamford" && contact.persons?.length === 0));
  // one save at a time: an answer in the view locks the page save, and the page save locks the contact
  const [answering, setAnswering] = useState(false);
  const onSave: OnSave = async (patch) => {
    setAnswering(true);
    try {
      return await saveHerdContact(herd.herd, patch);
    } finally {
      setAnswering(false);
    }
  };
  const save = () =>
    startTransition(async () => {
      setError(null);
      // Only what the admin changed: a stale start value must not overwrite a newer one.
      // Contact fields go through the contact editor below, never this PATCH.
      const patch: UpdateHerdFields = {};
      const shown: NonNullable<UpdateHerdFields["place_shown"]> = {};
      for (const key of ["wire_phone", "www"] as const)
        if (form[key] !== start[key]) {
          patch[key] = form[key] || null;
          shown[key] = { value: start[key] || null }; // the server saves only against it
        }
      if (form.is_active !== start.is_active) patch.is_active = form.is_active;
      if (Object.keys(patch).length === 0)
        return setError("Inga ändringar att spara.");
      if (Object.keys(shown).length) patch.place_shown = shown;
      const result = await updateHerd(herd.herd, patch);
      if (result?.status === 409 && result.type === "contact-changed") {
        // the form was out of date: fetch the herd again, and the form follows it
        setAfter(latest.current);
        setError(CONFLICT_TEXT);
        router.refresh();
      } else if (result?.error) setError(result.error); // success redirects
    });

  return (
    <section className={`sb-card ${ds["ad-form-card"]}`}>
      <div className={ds["ad-form-stack"]}>
        {error && (
          <div
            className={`${ds["ad-banner"]} ${ds["ad-banner-danger"]}`}
            role="alert"
          >
            {error}
          </div>
        )}
        <div className={ds["ad-form-row"]}>
          <h3 className={`sb-h6 ${ds["ad-section-title"]}`}>
            Kontakt för besättningen
          </h3>
          {!editing && (
            <button
              type="button"
              className="sb-btn sb-btn-ghost sb-btn-sm"
              aria-label="Redigera kontakt"
              disabled={pending || answering}
              onClick={() => setEditing(true)}
            >
              Redigera
            </button>
          )}
        </div>
        {missing && <p className="sb-meta">Kontakt saknas</p>}
        {editing ? (
          <ContactEditor
            herd={herd}
            contact={contact}
            onSave={onSave}
            onReload={() => router.refresh()}
            onDone={() => {
              setEditing(false);
              router.refresh();
            }}
            onCancel={() => setEditing(false)}
          />
        ) : (
          <ContactView
            herd={herd}
            contact={contact}
            onSave={onSave}
            onReload={() => router.refresh()}
            locked={pending}
          />
        )}
        <hr className="sb-rule" />
        {(
          [
            ["wire_phone", "Fast telefonnummer"],
            ["www", "Hemsida"],
          ] as const
        ).map(([key, label]) => (
          <div key={key}>
            <label className="sb-label" htmlFor={`herd-${key}`}>
              {label}
            </label>
            <input
              id={`herd-${key}`}
              className="sb-input"
              value={form[key]}
              onChange={(e) => setForm({ ...form, [key]: e.target.value })}
            />
          </div>
        ))}
        <FormControlLabel
          control={
            <Switch
              checked={form.is_active}
              onChange={(e) =>
                setForm({ ...form, is_active: e.target.checked })
              }
            />
          }
          label="Besättningen är aktiv"
        />
        <p className={ds["ad-note"]}>
          Om du inaktiverar besättningen visas den inte längre när en ägare
          väljs. All historik finns kvar. Besättningen kan inte tas bort
          permanent.
        </p>
        <div className={ds["ad-form-actions"]}>
          <button
            type="button"
            className="sb-btn"
            disabled={pending || editing || answering}
            onClick={save}
          >
            Spara
          </button>
        </div>

        <hr className="sb-rule" />

        <h3 className={`sb-h6 ${ds["ad-section-title"]}`}>
          {herd.owners.length > 1 ? `Ägare (${herd.owners.length})` : "Ägare"}
        </h3>
        <ul className={styles["ad-role-list"]}>
          {herd.owners.map((o) => (
            <li key={o.id} className={styles["ad-role-row"]}>
              <Link
                href={`/stamboken/admin/anvandare/${o.id}`}
                className={ds["ad-cell-link"]}
              >
                {o.username}
              </Link>
              {o.fullname && <span className="sb-meta">{o.fullname}</span>}
            </li>
          ))}
          {herd.owners.length === 0 && (
            <li className={styles["ad-role-row"]}>
              Besättningen har ingen ägare.
            </li>
          )}
        </ul>
        <p className={ds["ad-note"]}>
          En besättning kan ha flera ägare: huvudmedlemmen i medlemskapet som
          besättningen hör till, och konton med rollen Ägare för besättningen.
          Huvudmedlemmen ändras i matrikeln. Rollen Ägare läggs till och tas
          bort på användarsidan: öppna användaren ovan (eller via Alla
          användare).
        </p>
      </div>
    </section>
  );
}
