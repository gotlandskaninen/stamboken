"use client";

import { useState, useTransition } from "react";
import Link from "next/link";
import { FormControlLabel, Switch } from "@mui/material";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";
import { updateHerd } from "../actions";
import type { HerdDetail } from "./page";

export function HerdEditClient({ herd }: { herd: HerdDetail }) {
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  // DB lagrar adressen som en legacy-blob "gatuadress|postnummer|postort" —
  // dela upp för redigering (som legacy-formuläret) och slå ihop vid spara.
  const [street = "", zip = "", city = ""] = (
    herd.physical_address ?? ""
  ).split("|");
  const [form, setForm] = useState({
    name: herd.name ?? "",
    street,
    zip,
    city,
    email: herd.email ?? "",
    mobile_phone: herd.mobile_phone ?? "",
    wire_phone: herd.wire_phone ?? "",
    www: herd.www ?? "",
    is_active: herd.is_active,
  });
  const save = () =>
    startTransition(async () => {
      setError(null);
      // Pipe-format enbart när postnummer/postort finns — en ensam gatuadress
      // sparas utan pipes (legacy läser båda varianterna).
      const physicalAddress =
        form.zip || form.city
          ? `${form.street}|${form.zip}|${form.city}`
          : form.street || null;
      // Fields per the PATCH allow-list.
      const result = await updateHerd(herd.herd, {
        name: form.name || null,
        physical_address: physicalAddress,
        email: form.email || null,
        mobile_phone: form.mobile_phone || null,
        wire_phone: form.wire_phone || null,
        www: form.www || null,
        is_active: form.is_active,
      });
      if (result?.error) setError(result.error); // success redirects
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
        {(
          [
            ["name", "Namn"],
            ["email", "E-post"],
            ["mobile_phone", "Mobiltelefon"],
            ["wire_phone", "Fast telefonnummer"],
            ["street", "Gatuadress"],
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
        <div className={ds["ad-form-row"]}>
          <div>
            <label className="sb-label" htmlFor="herd-zip">
              Postnummer
            </label>
            <input
              id="herd-zip"
              className="sb-input"
              value={form.zip}
              onChange={(e) => setForm({ ...form, zip: e.target.value })}
            />
          </div>
          <div>
            <label className="sb-label" htmlFor="herd-city">
              Postort
            </label>
            <input
              id="herd-city"
              className="sb-input"
              value={form.city}
              onChange={(e) => setForm({ ...form, city: e.target.value })}
            />
          </div>
        </div>
        <div>
          <label className="sb-label" htmlFor="herd-www">
            Hemsida
          </label>
          <input
            id="herd-www"
            className="sb-input"
            value={form.www}
            onChange={(e) => setForm({ ...form, www: e.target.value })}
          />
        </div>
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
            disabled={pending}
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
          En besättning kan ha flera ägare. Ägarskapet hanteras på
          användarsidan: öppna användaren ovan (eller via Alla användare) och
          lägg till eller ta bort rollen Ägare för den här besättningen.
        </p>
      </div>
    </section>
  );
}
