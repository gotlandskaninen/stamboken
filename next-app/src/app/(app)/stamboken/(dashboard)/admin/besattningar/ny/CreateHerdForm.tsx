"use client";

import { useState, useTransition } from "react";
import { FormControlLabel, MenuItem, Switch, TextField } from "@mui/material";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";
import { createHerd } from "../actions";

// Mirrors legacy herdForm.tsx contactFields (name/email/mobile_phone/
// wire_phone/www/physical_address, each with a *_privacy companion).
const CONTACT_FIELDS = [
  { field: "name", label: "Namn" },
  { field: "email", label: "E-post" },
  { field: "mobile_phone", label: "Mobiltelefon" },
  { field: "wire_phone", label: "Fast telefonnummer" },
  { field: "www", label: "Hemsida" },
  { field: "physical_address", label: "Gatuadress" },
] as const;

type ContactField = (typeof CONTACT_FIELDS)[number]["field"];

const PRIVACY_OPTIONS = [
  { value: "private", label: "Inte offentligt" },
  { value: "authenticated", label: "Synligt för inloggade" },
  { value: "public", label: "Synligt för alla" },
];

export function CreateHerdForm({
  genebanks,
}: {
  genebanks: { id: number; name: string }[];
}) {
  const [pending, startTransition] = useTransition();
  const [genebankId, setGenebankId] = useState<number | "">(
    genebanks.length === 1 ? genebanks[0].id : "",
  );
  const [herdNumber, setHerdNumber] = useState("");
  const [herdName, setHerdName] = useState("");
  const [startDate, setStartDate] = useState("");
  const [isActive, setIsActive] = useState(true); // Aktiv defaults ON
  const [contact, setContact] = useState<Record<ContactField, string>>({
    name: "",
    email: "",
    mobile_phone: "",
    wire_phone: "",
    www: "",
    physical_address: "",
  });
  const [privacy, setPrivacy] = useState<Record<ContactField, string>>({
    name: "private",
    email: "private",
    mobile_phone: "private",
    wire_phone: "private",
    www: "private",
    physical_address: "private",
  });
  const [herdError, setHerdError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // Legacy convention (herdForm.tsx:392-421): genebank letter auto-prepended,
  // number manually chosen. Gotlandskanin → "G", Mellerudskanin → "M".
  const letter =
    genebankId === ""
      ? "?"
      : (genebanks.find((g) => g.id === genebankId)?.name[0] ?? "?");

  const numberValid = /^\d+$/.test(herdNumber);
  const canSubmit = genebankId !== "" && numberValid && !pending;

  const submit = () =>
    startTransition(async () => {
      setHerdError(null);
      setFormError(null);
      const result = await createHerd({
        genebank: genebankId as number,
        herd: `${letter}${herdNumber}`,
        is_active: isActive,
        herd_name: herdName || null,
        start_date: startDate || null,
        name: contact.name || null,
        name_privacy: contact.name ? privacy.name : null,
        email: contact.email || null,
        email_privacy: contact.email ? privacy.email : null,
        mobile_phone: contact.mobile_phone || null,
        mobile_phone_privacy: contact.mobile_phone
          ? privacy.mobile_phone
          : null,
        wire_phone: contact.wire_phone || null,
        wire_phone_privacy: contact.wire_phone ? privacy.wire_phone : null,
        www: contact.www || null,
        www_privacy: contact.www ? privacy.www : null,
        physical_address: contact.physical_address || null,
        physical_address_privacy: contact.physical_address
          ? privacy.physical_address
          : null,
      });
      // On success createHerd redirects and never returns.
      if (result?.field === "herd") setHerdError(result.error);
      else if (result?.error) setFormError(result.error);
    });

  return (
    <section className={`sb-card ${ds["ad-form-card"]}`}>
      <div className={ds["ad-form-stack"]}>
        {formError && (
          <div
            className={`${ds["ad-banner"]} ${ds["ad-banner-danger"]}`}
            role="alert"
          >
            {formError}
          </div>
        )}
        {/* MUI Select behålls: e2e/admin/12:30-31 öppnar listan med
            getByLabel("Genbank") + getByRole("option") — en native <select>
            skulle kräva selectOption och ändra beteendet. */}
        <TextField
          select
          required
          label="Genbank"
          value={genebankId}
          onChange={(e) => setGenebankId(Number(e.target.value))}
        >
          {genebanks.map((gb) => (
            <MenuItem key={gb.id} value={gb.id}>
              {gb.name}
            </MenuItem>
          ))}
        </TextField>
        <div>
          <label className="sb-label" htmlFor="herd-number">
            Besättningsnummer
          </label>
          <div className={styles["ad-input-prefix"]}>
            <span aria-hidden="true">{letter}</span>
            <input
              id="herd-number"
              required
              value={herdNumber}
              aria-describedby="herd-number-hint"
              className={`sb-input ${
                Boolean(herdError) || (herdNumber !== "" && !numberValid)
                  ? ds["ad-input-error"]
                  : ""
              }`}
              onChange={(e) => {
                setHerdError(null);
                setHerdNumber(e.target.value);
              }}
            />
          </div>
          <p
            id="herd-number-hint"
            className={herdError ? ds["ad-field-error"] : ds["ad-field-hint"]}
          >
            {herdError ??
              "Ange bara siffrorna — genbankens bokstav läggs till automatiskt. Numret väljer du själv."}
          </p>
        </div>
        <div>
          <label className="sb-label" htmlFor="herd-name">
            Besättningsnamn
          </label>
          <input
            id="herd-name"
            className="sb-input"
            value={herdName}
            onChange={(e) => setHerdName(e.target.value)}
          />
        </div>
        <div>
          <label className="sb-label" htmlFor="herd-start-date">
            Startdatum
          </label>
          <input
            id="herd-start-date"
            type="date"
            className="sb-input"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
          />
        </div>
        <FormControlLabel
          control={
            <Switch
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
            />
          }
          label="Besättningen är aktiv"
        />
        <h3 className={`sb-h6 ${ds["ad-section-title"]}`}>Kontaktperson</h3>
        {CONTACT_FIELDS.map(({ field, label }) => (
          <div key={field} className={ds["ad-form-row"]}>
            <div>
              <label className="sb-label" htmlFor={`contact-${field}`}>
                {label}
              </label>
              <input
                id={`contact-${field}`}
                className="sb-input"
                value={contact[field]}
                onChange={(e) =>
                  setContact({ ...contact, [field]: e.target.value })
                }
              />
            </div>
            <TextField
              select
              label="Synlighet"
              value={privacy[field]}
              size="small"
              onChange={(e) =>
                setPrivacy({ ...privacy, [field]: e.target.value })
              }
            >
              {PRIVACY_OPTIONS.map((o) => (
                <MenuItem key={o.value} value={o.value}>
                  {o.label}
                </MenuItem>
              ))}
            </TextField>
          </div>
        ))}
        <div className={ds["ad-form-actions"]}>
          <button
            type="button"
            className="sb-btn"
            disabled={!canSubmit}
            onClick={submit}
          >
            Skapa besättning
          </button>
        </div>
      </div>
    </section>
  );
}
