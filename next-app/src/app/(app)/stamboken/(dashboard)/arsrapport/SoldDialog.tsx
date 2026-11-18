"use client";

import React from "react";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  Autocomplete,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import {
  BuyerFields,
  EMPTY_BUYER,
  buyerComplete,
  buyerPayload,
  type BuyerDraft,
} from "@/components/individual/BuyerFields";
import type { getGenebankHerds } from "../individ/[number]/actions";
import { isOutsideGenebankHerd, type GenebankHerd } from "@/utils/saleRules";
import { MONTHS, storedSale, type BodyEntry, type SaldState } from "./lib";
import styles from "./arsrapport.module.css";

interface Props {
  open: boolean;
  number: string;
  year: number;
  genebankId: number;
  ownHerd: string; // the seller's herd: not a buyer
  // The picker's data, as SellRabbitDialog gets it (getGenebankHerds).
  loadHerds: typeof getGenebankHerds;
  existing: SaldState | null; // a saved sale: its buyer fields start empty (Task 6)
  submitted: BodyEntry["sald"] | null; // the sale in the report's latest submission, whose buyer is stored
  canSell: boolean; // a proposal takes no kept buyer (F1, K1)
  onSave: (s: SaldState) => void;
  onClose: () => void;
}

// The step-2 herd picker: the genebank's active herds, not `ownHerd` and not
// GX1/MX1 ("Utanför genbanken" is its own choice). Also the purchase dialog's.
export function HerdPicker({
  genebankId,
  ownHerd,
  loadHerds,
  label,
  value,
  onChange,
  error,
}: {
  genebankId: number;
  ownHerd: string;
  loadHerds: typeof getGenebankHerds;
  label: string;
  value: string;
  onChange: (herd: string) => void;
  error?: string | null; // beside the field, as its description
}) {
  const [loaded, setLoaded] = React.useState<Awaited<
    ReturnType<typeof getGenebankHerds>
  > | null>(null);

  React.useEffect(() => {
    if (loaded !== null) return;
    let cancelled = false;
    loadHerds(genebankId)
      .then((r) => {
        if (!cancelled) setLoaded(r);
      })
      .catch(() => {
        // a broken connection must not leave the picker waiting for ever
        if (!cancelled)
          setLoaded({ success: false as const, error: "unexpected_error" });
      });
    return () => {
      cancelled = true;
    };
  }, [loaded, loadHerds, genebankId]);
  const herds = loaded?.success ? loaded.herds : null;
  const options = React.useMemo(
    () =>
      (herds ?? [])
        .filter(
          (h) =>
            h.is_active && h.herd !== ownHerd && !isOutsideGenebankHerd(h.herd),
        )
        .sort((a, b) => a.herd.localeCompare(b.herd, "sv", { numeric: true })),
    [herds, ownHerd],
  );
  const target = options.find((h) => h.herd === value) ?? null;
  const optionLabel = (h: GenebankHerd) =>
    h.herd_name ? `${h.herd} – ${h.herd_name}` : h.herd;

  return (
    <>
      <Autocomplete
        options={options}
        value={target}
        onChange={(_, h) => onChange(h?.herd ?? "")}
        getOptionLabel={optionLabel}
        isOptionEqualToValue={(a, b) => a.herd === b.herd}
        loading={loaded === null}
        loadingText="Hämtar besättningar …"
        noOptionsText="Ingen besättning matchar"
        renderInput={(params) => (
          <TextField
            {...params}
            label={label}
            error={!!error}
            helperText={error}
          />
        )}
      />
      {loaded && !loaded.success && (
        <p className={styles.errorText} role="alert">
          Det gick inte att hämta besättningarna.{" "}
          <button
            type="button"
            className="sb-btn sb-btn-secondary sb-btn-sm"
            onClick={() => setLoaded(null)}
          >
            Försök igen
          </button>
        </p>
      )}
    </>
  );
}

// The buyer outside the genebank is held in memory by the caller and never
// reaches the draft or localStorage.
function Body({
  number,
  year,
  genebankId,
  ownHerd,
  loadHerds,
  existing,
  submitted,
  canSell,
  onSave,
  onClose,
}: Props) {
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [outside, setOutside] = React.useState(existing?.till === "utanfor");
  const [code, setCode] = React.useState(
    existing && existing.till !== "utanfor" ? existing.till : "",
  );
  const [ar, setAr] = React.useState(existing?.ar ?? year);
  const [manad, setManad] = React.useState<number | null>(
    existing?.manad ?? null,
  );
  const [dag, setDag] = React.useState(
    existing?.dag ? String(existing.dag) : "",
  );
  const [buyer, setBuyer] = React.useState<BuyerDraft>({
    ...EMPTY_BUYER,
    ...existing?.kopare,
  });
  // K1: a buyer kept across Dra tillbaka, which the seller never reads back. A
  // proposal cannot take it (F1), so a role that may not sell types the buyer.
  const keptId = existing?.kopare_id != null && !existing.kopare;
  const kept = canSell && keptId;
  // A sale the report holds, unchanged here: its buyer is stored. A sale only in
  // the draft, or a changed one, needs the buyer again, as Skicka does.
  const stored =
    outside &&
    storedSale(
      { till: "utanfor", ar, manad, dag: dag ? Number(dag) : null },
      submitted,
    );
  const [tried, setTried] = React.useState(false);
  const typed = [
    buyer.name,
    buyer.town,
    buyer.postal_address,
    buyer.email,
    buyer.phone,
  ].some((v) => v.trim());
  const buyerHalf = typed && !buyerComplete(buyer);
  const buyerMissing = outside && !kept && !stored && !buyerComplete(buyer);
  const buyerWanted = outside && (buyerMissing || buyerHalf);
  // Each refusal beside its field, all at once once Spara is pressed.
  const errors = {
    // code is only ever the picker's own choice or the saved buyer, so it needs
    // no list: a slow herd list must not turn Spara into a silent refusal
    herd:
      !outside && !code
        ? "Välj en besättning i genbanken, eller Utanför genbanken."
        : null,
    name: buyerWanted && !buyer.name.trim() ? "Skriv köparens namn." : null,
    town: buyerWanted && !buyer.town.trim() ? "Skriv köparens ort." : null,
    month: manad === null ? "Välj månad." : null,
  };
  const problem = Object.values(errors).some(Boolean);
  const shown = (e: string | null) => (tried ? e : null);
  const content = React.useRef<HTMLDivElement>(null);
  const [attempt, setAttempt] = React.useState(0);
  React.useEffect(() => {
    // Spara refused: the first field in error takes the focus, and is scrolled to
    if (attempt)
      content.current
        ?.querySelector<HTMLElement>('[aria-invalid="true"]')
        ?.focus();
  }, [attempt]);

  const save = () => {
    setTried(true);
    if (problem) return setAttempt((n) => n + 1);
    onSave({
      till: outside ? "utanfor" : code,
      ar,
      manad,
      dag: dag ? Number(dag) : null,
      kopare: outside && buyerComplete(buyer) ? buyerPayload(buyer) : null,
      ...(outside && existing?.kopare_id != null
        ? { kopare_id: existing.kopare_id }
        : {}),
    });
  };

  return (
    <Dialog
      open
      onClose={onClose}
      fullScreen={mobile}
      fullWidth
      maxWidth="sm"
      aria-labelledby="sold-title"
    >
      <DialogTitle id="sold-title" sx={{ pr: 6 }}>
        Såld: {number}
        <IconButton
          aria-label="Stäng"
          onClick={onClose}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent ref={content} dividers={mobile} className={styles.detail}>
        <div className={styles.choices} role="radiogroup" aria-label="Köparen">
          <label className={styles.choice}>
            <input
              type="radio"
              name="sold-to"
              checked={!outside}
              onChange={() => setOutside(false)}
            />
            <span>Besättning i genbanken</span>
          </label>
          <label className={styles.choice}>
            <input
              type="radio"
              name="sold-to"
              checked={outside}
              onChange={() => setOutside(true)}
            />
            <span>Utanför genbanken</span>
          </label>
        </div>
        {!outside && (
          <HerdPicker
            genebankId={genebankId}
            ownHerd={ownHerd}
            loadHerds={loadHerds}
            label="Köparens besättning"
            value={code}
            onChange={setCode}
            error={shown(errors.herd)}
          />
        )}
        {outside && (
          <>
            {kept ? (
              <p className={styles.meta}>
                Köparen finns sparad. Lämna fälten tomma om köparen är rätt,
                eller skriv en ny köpare.
              </p>
            ) : (
              stored && (
                <p className={styles.meta}>
                  Köparens uppgifter sparas inte i rapporten. Lämna fälten tomma
                  om köparen är rätt, och fyll i dem om du vill rätta köparen.
                </p>
              )
            )}
            <BuyerFields
              variant="member"
              value={buyer}
              onChange={setBuyer}
              errors={{
                name: shown(errors.name) ?? undefined,
                town: shown(errors.town) ?? undefined,
              }}
            />
            {!kept && (
              <p className={styles.meta}>
                Köparens uppgifter sparas när du skickar rapporten, inte innan.
              </p>
            )}
          </>
        )}
        <div className={styles.grid2}>
          <label className={styles.label}>
            År
            <select
              className={styles.field}
              style={{ width: "100%" }}
              value={ar}
              onChange={(e) => setAr(Number(e.target.value))}
            >
              {[year, year + 1].map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </select>
          </label>
          <div>
            <label className={styles.label}>
              Månad
              <select
                className={styles.field}
                style={{ width: "100%" }}
                value={manad ?? ""}
                aria-invalid={!!shown(errors.month)}
                aria-describedby={
                  shown(errors.month) ? "sold-month-error" : undefined
                }
                onChange={(e) =>
                  setManad(e.target.value ? Number(e.target.value) : null)
                }
              >
                <option value="">Välj månad</option>
                {MONTHS.map((m, i) => (
                  <option key={m} value={i + 1}>
                    {m}
                  </option>
                ))}
              </select>
            </label>
            {shown(errors.month) && (
              <p id="sold-month-error" className={styles.errorText}>
                {errors.month}
              </p>
            )}
          </div>
          <label className={styles.label}>
            Dag (frivillig)
            <input
              className={styles.field}
              style={{ width: "100%", boxSizing: "border-box" }}
              inputMode="numeric"
              maxLength={2}
              value={dag}
              onChange={(e) => setDag(e.target.value.replace(/\D/g, ""))}
            />
          </label>
        </div>
      </DialogContent>
      <DialogActions
        sx={{
          position: "sticky",
          bottom: 0,
          gap: 1,
          flexDirection: mobile ? "column-reverse" : "row",
          "& > *": mobile ? { width: "100%", ml: "0 !important" } : {},
        }}
      >
        <button
          type="button"
          className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
          onClick={onClose}
        >
          Avbryt
        </button>
        <button type="button" className={`sb-btn ${styles.btn}`} onClick={save}>
          Spara försäljningen
        </button>
      </DialogActions>
    </Dialog>
  );
}

export function SoldDialog(props: Props) {
  return props.open ? <Body {...props} /> : null;
}
