"use client";

import React from "react";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { getGenebankHerds } from "../individ/[number]/actions";
import type { ActionResult } from "../inkorg/actions";
import {
  NOT_IN_STAMBOKEN_TEXT,
  PURCHASE_SENT_TEXT,
  todayStockholm,
  type PurchaseNotice,
} from "./lib";
import { HerdPicker } from "./SoldDialog";
import styles from "./arsrapport.module.css";

export interface PurchaseBody {
  number: string;
  from_herd: string; // a herd's number, or "utanfor"
  date: string;
}

interface Props {
  open: boolean;
  year: number;
  genebankId: number;
  ownHerd: string; // the buyer's herd: not a seller
  loadHerds: typeof getGenebankHerds; // as SoldDialog gets it; the link's own list behind the link
  send: (body: PurchaseBody) => Promise<ActionResult<PurchaseNotice>>;
  onSent: () => void;
  onClose: () => void;
}

// "Anmäl ett köp" (4a Task 5): a rabbit bought during the year that Stamboken
// has not moved into the herd. The genebank manager registers the purchase.
function Body({
  year,
  genebankId,
  ownHerd,
  loadHerds,
  send,
  onSent,
  onClose,
}: Props) {
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [number, setNumber] = React.useState("");
  const [outside, setOutside] = React.useState(false);
  const [code, setCode] = React.useState("");
  const [date, setDate] = React.useState("");
  const [tried, setTried] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [refused, setRefused] = React.useState<string | null>(null);
  const [missing, setMissing] = React.useState(false); // the number is not in Stamboken
  const [sent, setSent] = React.useState(false);
  const today = todayStockholm();
  const last = `${year}-12-31` < today ? `${year}-12-31` : today;
  const problem =
    (!number.trim() && "Skriv kaninens nummer.") ||
    (!outside &&
      !code &&
      "Välj en besättning i genbanken, eller Utanför genbanken.") ||
    (!date && "Välj datum för köpet.") ||
    null;

  const submit = async () => {
    setTried(true);
    if (problem || busy) return;
    setBusy(true);
    setRefused(null);
    setMissing(false);
    try {
      const res = await send({
        number: number.trim(),
        from_herd: outside ? "utanfor" : code,
        date,
      });
      if (res.ok) {
        setSent(true);
        onSent();
      } else if (res.problem.extensions?.code === "inte_i_stamboken")
        setMissing(true);
      else setRefused(res.problem.detail || res.problem.title);
    } catch {
      setRefused("Det gick inte att nå servern. Försök igen.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onClose={busy ? undefined : onClose}
      fullScreen={mobile}
      fullWidth
      maxWidth="sm"
      aria-labelledby="purchase-title"
    >
      <DialogTitle id="purchase-title" sx={{ pr: 6 }}>
        Anmäl ett köp
        <IconButton
          aria-label="Stäng"
          onClick={onClose}
          disabled={busy}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers={mobile} className={styles.detail}>
        {sent ? (
          <p role="status">{PURCHASE_SENT_TEXT}</p>
        ) : (
          <>
            <label className={styles.label}>
              Kaninens nummer
              <input
                className={styles.field}
                style={{ width: "100%", boxSizing: "border-box" }}
                autoComplete="off"
                value={number}
                onChange={(e) => {
                  setNumber(e.target.value);
                  setMissing(false);
                }}
              />
            </label>
            {/* shortcut: the "Lägg till från intyget" button opens 4b's AddRabbit once merged */}
            <p
              className={missing ? styles.errorText : styles.meta}
              role={missing ? "alert" : undefined}
            >
              {NOT_IN_STAMBOKEN_TEXT}
            </p>
            <div
              className={styles.choices}
              role="radiogroup"
              aria-label="Säljarens besättning"
            >
              <label className={styles.choice}>
                <input
                  type="radio"
                  name="bought-from"
                  checked={!outside}
                  onChange={() => setOutside(false)}
                />
                <span>Besättning i genbanken</span>
              </label>
              <label className={styles.choice}>
                <input
                  type="radio"
                  name="bought-from"
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
                label="Säljarens besättning"
                value={code}
                onChange={setCode}
              />
            )}
            <label className={styles.label}>
              Datum för köpet
              <input
                type="date"
                className={styles.field}
                style={{ width: "100%", boxSizing: "border-box" }}
                min={`${year}-01-01`}
                max={last}
                value={date}
                onChange={(e) => setDate(e.target.value)}
              />
            </label>
            {((tried && problem) || refused) && (
              <p className={styles.errorText} role="alert">
                {(tried && problem) || refused}
              </p>
            )}
          </>
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
        {sent ? (
          <button
            type="button"
            className={`sb-btn ${styles.btn}`}
            onClick={onClose}
          >
            Stäng
          </button>
        ) : (
          <>
            <button
              type="button"
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
              onClick={onClose}
              disabled={busy}
            >
              Avbryt
            </button>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              onClick={submit}
              disabled={busy}
            >
              {busy ? "Skickar…" : "Skicka anmälan"}
            </button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}

export function PurchaseDialog(props: Props) {
  return props.open ? <Body {...props} /> : null;
}
