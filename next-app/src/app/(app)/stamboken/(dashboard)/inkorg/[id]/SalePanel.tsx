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
  buyerMode,
  buyerModes,
  buyerPayload,
  saleYear,
  type BuyerDraft,
} from "@/components/individual/BuyerFields";
import { ProposalChecks } from "@/components/register/RegisterFromCertificate";
import { rabbitSales, registerSale, type RegistrySale } from "../actions";
import {
  buildSalePayload,
  outsideHerd,
  problemField,
  provenSale,
  shownProposal,
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
  addressRequired = false,
}: {
  itemId: number;
  doc: InboxDocument;
  herds: GenebankHerd[];
  canSave: boolean;
  onDone: (document: InboxDocument) => void;
  /** As the API: a new sale needs the buyer's postal address unless a manager or admin registers it (#111). */
  addressRequired?: boolean;
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
  const year = saleYear(form.date); // the buyer's choice follows it (#273)
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [pending, start] = useTransition();
  const set = (changes: Partial<SaleForm>) =>
    setForm((f) => ({ ...f, ...changes }));
  // The seller and buyer read off the photo (rule 5 b): shown, and filled in only when the handler clicks.
  const read = shownProposal(doc)?.sale;
  // The e-mail read off the photo is only for the association's notice (#273): it goes as soon as the notice is not
  // the choice, so that the bevis's yes never makes it a contact address. One edited by hand stays.
  const [photoEmail, setPhotoEmail] = useState<string | null>(null);
  const changeBuyer = (next: BuyerDraft, y = year) => {
    if (photoEmail !== null && buyerMode(next, y) !== "epost") {
      setPhotoEmail(null);
      setBuyer(next.email === photoEmail ? { ...next, email: "" } : next);
    } else setBuyer(next);
  };
  // A herd number read that is not the genebank's: the handler chooses the herd or a buyer outside.
  const [choose, setChoose] = useState(false);
  // The reading the form was filled from: once it changes or goes (the item closed and opened again), so does what
  // it filled, and the save says it came from the photo, so the server refuses it without a reading.
  const readKey = read ? JSON.stringify(read) : null;
  const [filledFrom, setFilledFrom] = useState<string | null>(null);
  if (filledFrom !== null && filledFrom !== readKey) {
    setFilledFrom(null);
    setPhotoEmail(null);
    setChoose(false);
    setBuyer(EMPTY_BUYER);
    setForm((f) => ({ ...f, herd: "", outside: false, date: "" }));
    setFormError("Läsningen har ändrats, fyll i köparen igen.");
  }
  const fill = () => {
    if (!read) return;
    const date = read.date ?? form.date;
    setFilledFrom(readKey);
    setFormError(null);
    setChoose(!!read.buyer_herd && !read.buyer_herd.found);
    setPhotoEmail(null);
    setBuyer(EMPTY_BUYER); // never what was typed before
    if (read.buyer_herd?.found) {
      set({ herd: read.buyer_herd.herd, outside: false, date });
    } else if (read.buyer && !read.buyer_herd) {
      const { name, town, postal_address, email } = read.buyer;
      // The e-mail only in the years that have the notice; never a yes for the buyer.
      const notice = !!email && buyerModes(saleYear(date)).includes("epost");
      set({ outside: true, date });
      setPhotoEmail(notice ? email : null);
      setBuyer({
        ...EMPTY_BUYER,
        name,
        town,
        postal_address,
        ...(notice ? { email, mode: "epost" as const } : {}),
      });
    } else {
      set({ herd: "", outside: false, date }); // a herd read that is not the genebank's: no choice is made
    }
  };
  const lines = (
    [
      ["Köparens besättning", read?.buyer_herd?.herd],
      ["Köpare", read?.buyer?.name],
      ["Postadress", read?.buyer?.postal_address],
      ["Ort", read?.buyer?.town],
      ["E-post", read?.buyer?.email],
      ["Säljdatum", read?.date],
      ["Säljarens besättning", read?.seller_herd],
    ] as const
  ).filter(([, value]) => value);
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
  // The buyer is asked for unless the registered sale has one, or had one that was removed.
  const saleRegistered = !!registered && registered.buyer !== "none";

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    start(async () => {
      setErrors({});
      setFormError(null);
      const payload = {
        ...buildSalePayload(form),
        ...(filledFrom !== null ? { from_photo: true as const } : {}),
      };
      const res = await registerSale(
        itemId,
        doc.id,
        form.outside && !saleRegistered
          ? { ...payload, buyer: buyerPayload(buyer, year) }
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

  // Saved: the sale and its buyer are in Stamboken, the one place for them; nothing here can send it again.
  if (saved || doc.herd_tracking_id != null)
    return (
      <div className={styles.card}>
        <h2 className={styles.cardTitle}>Försäljning</h2>
        <p role="status" className={styles.muted}>
          Försäljningen är sparad.
        </p>
      </div>
    );

  return (
    <form className={styles.card} onSubmit={submit}>
      <h2 className={styles.cardTitle}>Försäljning</h2>
      {!proof && (
        <p className={styles.note}>
          En försäljning utan bevis markerar ärendet med &quot;bevis
          saknas&quot;.
        </p>
      )}
      {read && (
        <div className={styles.note}>
          <strong>Från fotot</strong>
          <ul aria-label="Från fotot">
            {lines.map(([label, value]) => (
              <li key={label}>
                {label}: {value}
              </li>
            ))}
          </ul>
          <ProposalChecks checks={read.checks} />
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            onClick={fill}
          >
            Fyll i från fotot
          </button>
          {choose && (
            <p role="status">
              Köparens besättning på fotot finns inte i genbanken. Välj
              besättningen, eller kryssa i Köparen är utanför föreningen.
            </p>
          )}
        </div>
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
          onChange={(e) => {
            set({ date: e.target.value });
            changeBuyer(buyer, saleYear(e.target.value));
          }}
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
                <BuyerFields
                  value={buyer}
                  onChange={changeBuyer}
                  year={year}
                  size="small"
                  addressRequired={addressRequired}
                />
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
      <div className={styles.submitRow}>
        <button
          type="submit"
          className="sb-btn"
          disabled={
            !canSave ||
            pending ||
            (!form.outside && !form.herd.trim()) ||
            (form.outside &&
              !saleRegistered &&
              !buyerComplete(buyer, addressRequired, year)) ||
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
