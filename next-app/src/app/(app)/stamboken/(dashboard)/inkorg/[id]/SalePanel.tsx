"use client";

import { useEffect, useState, useTransition } from "react";
import {
  Autocomplete,
  Checkbox,
  FormControlLabel,
  TextField,
} from "@mui/material";
import type { GenebankHerd } from "@/utils/saleRules";
import {
  BuyerFields,
  EMPTY_BUYER,
  buyerComplete,
  buyerPayload,
} from "@/components/individual/BuyerFields";
import { rabbitSales, registerSale, type RegistrySale } from "../actions";
import {
  buildSalePayload,
  outsideHerd,
  problemField,
  provenSale,
  type InboxDocument,
  type SaleForm,
} from "../lib";
import styles from "../inkorg.module.css";

/** The rabbit is looked up once typing pauses, not on every key. */
export const LOOKUP_DELAY_MS = 300;

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
  const [buyer, setBuyer] = useState(EMPTY_BUYER);
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, start] = useTransition();
  const set = (changes: Partial<SaleForm>) =>
    setForm((f) => ({ ...f, ...changes }));
  const names = new Map(herds.map((h) => [h.herd, h.herd_name]));
  const proof = doc.doc_type === "bevis";
  // The rabbit's active sales, read through the item: a proof of a sale already registered asks for no buyer
  // unless that sale has none (provenSale). Kept with the number they belong to, so another number's rows never
  // hide the buyer fields; `rows` null means the lookup failed, and the panel says so rather than guess.
  const [sales, setSales] = useState<{
    number: string;
    rows: RegistrySale[] | null;
  }>({ number: "", rows: [] });
  const number = buildSalePayload(form).individual;
  useEffect(() => {
    if (!proof || !number) return;
    let current = true;
    const timer = setTimeout(() => {
      rabbitSales(itemId, number).then((res) => {
        if (current) setSales({ number, rows: res.ok ? res.data.sales : null });
      });
    }, LOOKUP_DELAY_MS);
    return () => {
      current = false;
      clearTimeout(timer);
    };
  }, [proof, itemId, number]);
  const lookedUp = proof && !!number && sales.number === number;
  const lookupFailed = lookedUp && sales.rows === null;
  const registered = lookedUp
    ? provenSale(doc, buildSalePayload(form), sales.rows ?? [])
    : null;
  // The buyer is asked for unless the registered sale has one.
  const saleRegistered = !!registered?.has_buyer;

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    start(async () => {
      setErrors({});
      setFormError(null);
      const payload = buildSalePayload(form);
      const res = await registerSale(
        itemId,
        doc.id,
        form.outside && !saleRegistered
          ? { ...payload, buyer: buyerPayload(buyer) }
          : payload,
      );
      if (res.ok) {
        setSaved(true);
        onDone(res.data.document);
        return;
      }
      const field = problemField(res.problem);
      // The herd field is hidden for a buyer outside the association.
      const shown = ["individual", "date", ...(form.outside ? [] : ["herd"])];
      if (field && shown.includes(field))
        setErrors({ [field]: res.problem.detail });
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
            <>
              <p className={styles.muted}>
                Sparas på {outsideHerd(form.individual) ?? "GX1 eller MX1"}.
              </p>
              {!saleRegistered && (
                <BuyerFields value={buyer} onChange={setBuyer} size="small" />
              )}
            </>
          ) : (
            <Autocomplete
              freeSolo
              options={herds.map((h) => h.herd)}
              getOptionLabel={(h) =>
                names.get(h) ? `${h} – ${names.get(h)}` : h
              }
              inputValue={form.herd}
              onInputChange={(_, v) => set({ herd: v })}
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
      {form.outside && lookupFailed && (
        <p role="alert" className={styles.error}>
          Kunde inte läsa kaninens försäljningar, så det går inte att veta om
          köparen redan är registrerad. Kontrollera individnumret.
        </p>
      )}
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
        <button
          type="submit"
          className="sb-btn"
          disabled={
            !canSave ||
            pending ||
            (form.outside && !saleRegistered && !buyerComplete(buyer)) ||
            (form.outside && (lookupFailed || (proof && !lookedUp)))
          }
        >
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
