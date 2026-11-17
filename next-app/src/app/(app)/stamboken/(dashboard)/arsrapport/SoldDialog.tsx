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
import { MONTHS, type SaldState } from "./lib";
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
}: {
  genebankId: number;
  ownHerd: string;
  loadHerds: typeof getGenebankHerds;
  label: string;
  value: string;
  onChange: (herd: string) => void;
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
        renderInput={(params) => <TextField {...params} label={label} />}
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
  const [tried, setTried] = React.useState(false);
  const typed = [
    buyer.name,
    buyer.town,
    buyer.postal_address,
    buyer.email,
    buyer.phone,
  ].some((v) => v.trim());
  const buyerHalf = typed && !buyerComplete(buyer);
  const buyerMissing =
    outside && (!existing || (keptId && !canSell)) && !buyerComplete(buyer);
  const problem =
    // code is only ever the picker's own choice or the saved buyer, so it needs
    // no list: a slow herd list must not turn Spara into a silent refusal
    (!outside &&
      !code &&
      "Välj en besättning i genbanken, eller Utanför genbanken.") ||
    (manad === null && "Välj månad.") ||
    (outside &&
      (buyerMissing || buyerHalf) &&
      "Skriv köparens namn och ort.") ||
    null;

  const save = () => {
    setTried(true);
    if (problem) return;
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
      <DialogContent dividers={mobile} className={styles.detail}>
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
              existing &&
              !keptId && (
                <p className={styles.meta}>
                  Köparens uppgifter sparas inte i rapporten. Lämna fälten tomma
                  om köparen är rätt, och fyll i dem om du vill rätta köparen.
                </p>
              )
            )}
            <BuyerFields value={buyer} onChange={setBuyer} />
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
          <label className={styles.label}>
            Månad
            <select
              className={styles.field}
              style={{ width: "100%" }}
              value={manad ?? ""}
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
        {tried && problem && (
          <p className={styles.errorText} role="alert">
            {problem}
          </p>
        )}
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
