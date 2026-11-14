"use client";

import { useState, useTransition } from "react";
import {
  Autocomplete,
  Checkbox,
  FormControlLabel,
  TextField,
} from "@mui/material";
import type { GenebankHerd } from "@/utils/saleRules";
import { registerSale } from "../actions";
import {
  buildSalePayload,
  outsideHerd,
  problemField,
  type InboxDocument,
  type SaleForm,
} from "../lib";
import styles from "../inkorg.module.css";

/** A sale the document shows, saved with …/overlat. */
export function SalePanel({
  itemId,
  doc,
  herds,
  canSave,
  onDone,
}: {
  itemId: number;
  doc: InboxDocument;
  herds: GenebankHerd[];
  canSave: boolean;
  onDone: (document: InboxDocument) => void;
}) {
  const [form, setForm] = useState<SaleForm>({
    individual: doc.individual ?? "",
    herd: "",
    outside: false,
    date: "",
  });
  const [errors, setErrors] = useState<Partial<Record<keyof SaleForm, string>>>(
    {},
  );
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, start] = useTransition();
  const set = (changes: Partial<SaleForm>) =>
    setForm((f) => ({ ...f, ...changes }));
  const names = new Map(herds.map((h) => [h.herd, h.herd_name]));
  const proof = doc.doc_type === "bevis";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    start(async () => {
      setErrors({});
      setFormError(null);
      const res = await registerSale(itemId, doc.id, buildSalePayload(form));
      if (res.ok) {
        setSaved(true);
        onDone(res.data.document);
        return;
      }
      const field = problemField(res.problem);
      if (field && field in form) setErrors({ [field]: res.problem.detail });
      else setFormError(res.problem.detail);
    });
  };

  return (
    <form className={styles.card} onSubmit={submit}>
      <h2 className={styles.cardTitle}>Försäljning</h2>
      {!proof && (
        <p className={styles.note}>
          En försäljning utan bevis markerar ärendet med &quot;bevis
          saknas&quot;.
        </p>
      )}
      <div className={styles.fields}>
        <TextField
          label="Individnummer"
          value={form.individual}
          onChange={(e) => set({ individual: e.target.value })}
          error={!!errors.individual}
          helperText={errors.individual}
          placeholder="G1274-2512"
          size="small"
          required
        />
        <TextField
          label="Säljdatum"
          type="date"
          value={form.date}
          onChange={(e) => set({ date: e.target.value })}
          error={!!errors.date}
          helperText={errors.date}
          size="small"
          required
          slotProps={{ inputLabel: { shrink: true } }}
        />
        <div className={styles.wide}>
          <FormControlLabel
            control={
              <Checkbox
                checked={form.outside}
                onChange={(e) => set({ outside: e.target.checked })}
              />
            }
            label="Köparen är utanför föreningen"
          />
        </div>
        <div className={styles.wide}>
          {form.outside ? (
            <p className={styles.muted}>
              Sparas på {outsideHerd(form.individual) ?? "GX1 eller MX1"}.
              Köparens namn och adress sparas inte; de finns bara på
              originalfotot.
            </p>
          ) : (
            <Autocomplete
              freeSolo
              options={herds.map((h) => h.herd)}
              getOptionLabel={(h) =>
                names.get(h) ? `${h} – ${names.get(h)}` : h
              }
              inputValue={form.herd}
              onInputChange={(_, v, reason) =>
                set({ herd: reason === "reset" ? v.split(" ")[0] : v })
              }
              renderInput={(params) => (
                <TextField
                  {...params}
                  label="Köparens besättning"
                  size="small"
                  required
                  error={!!errors.herd}
                  helperText={errors.herd}
                />
              )}
            />
          )}
        </div>
      </div>
      {formError && (
        <p role="alert" className={styles.error}>
          {formError}
        </p>
      )}
      {saved && !proof && (
        <p role="status" className={styles.muted}>
          Försäljningen är sparad.
        </p>
      )}
      <div className={styles.submitRow}>
        <button type="submit" className="sb-btn" disabled={!canSave || pending}>
          {pending
            ? "Sparar…"
            : proof
              ? "Spara och nästa"
              : "Spara försäljningen"}
        </button>
      </div>
    </form>
  );
}
