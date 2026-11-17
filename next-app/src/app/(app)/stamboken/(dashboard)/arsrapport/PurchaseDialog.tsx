"use client";

import React from "react";
import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  LinearProgress,
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
  type PurchaseBody,
  type PurchaseNotice,
} from "./lib";
import { HerdPicker } from "./SoldDialog";
import { MAX_BYTES } from "./AddRabbit";
import { prepare } from "../inskick/ny/prepare";
import styles from "./arsrapport.module.css";

type Photo = {
  status: "tom" | "skickar" | "klar" | "fel";
  document_id?: number;
  error?: string;
};
const PHOTO_TYPE_TEXT = "Välj om fotot visar överlåtelsebeviset eller intyget.";

interface Props {
  open: boolean;
  year: number;
  genebankId: number;
  ownHerd: string; // the buyer's herd: not a seller
  loadHerds: typeof getGenebankHerds; // as SoldDialog gets it; the link's own list behind the link
  send: (body: PurchaseBody) => Promise<ActionResult<PurchaseNotice>>;
  upload: (
    data: FormData,
  ) => Promise<ActionResult<{ item_id: number; document_id: number }>>; // the report's photo upload (4b)
  onAddRabbit?: () => void; // the report's "Lägg till kanin från intyget", where the report offers it
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
  upload,
  onAddRabbit,
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
  const [photo, setPhoto] = React.useState<Photo>({ status: "tom" });
  const [docType, setDocType] = React.useState<"bevis" | "intyg" | null>(null);
  const attempt = React.useRef(0); // a newer photo's upload drops an earlier one's answer
  const today = todayStockholm();
  const last = `${year}-12-31` < today ? `${year}-12-31` : today;
  const problem =
    (!number.trim() && "Skriv kaninens nummer.") ||
    (!outside &&
      !code &&
      "Välj en besättning i genbanken, eller Utanför genbanken.") ||
    (!date && "Välj datum för köpet.") ||
    (photo.status === "klar" && !docType && PHOTO_TYPE_TEXT) ||
    null;

  const pick = async (file: File | undefined) => {
    if (!file) return;
    const mine = ++attempt.current;
    setPhoto({ status: "skickar" });
    let next: Photo;
    try {
      const prepared = await prepare(file);
      if (prepared.size > MAX_BYTES)
        next = { status: "fel", error: "Filen är för stor. Max 10 MB." };
      else {
        const data = new FormData();
        data.set("file", prepared);
        const res = await upload(data);
        next = res.ok
          ? { status: "klar", document_id: res.data.document_id }
          : { status: "fel", error: res.problem.detail };
      }
    } catch {
      next = { status: "fel", error: "Uppladdningen avbröts. Försök igen." };
    }
    if (attempt.current === mine) setPhoto(next);
  };

  const submit = async () => {
    setTried(true);
    if (problem || busy || photo.status === "skickar") return;
    setBusy(true);
    setRefused(null);
    setMissing(false);
    try {
      const res = await send({
        number: number.trim(),
        from_herd: outside ? "utanfor" : code,
        date,
        ...(photo.status === "klar" && docType
          ? { document_id: photo.document_id, doc_type: docType }
          : {}),
      });
      if (res.ok) {
        setSent(true);
        onSent();
      } else if (res.problem.extensions?.code === "inte_i_stamboken")
        setMissing(true);
      else if (res.problem.extensions?.field === "photo")
        setPhoto({ status: "fel", error: res.problem.detail }); // chosen again
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
            <p
              className={missing ? styles.errorText : styles.meta}
              role={missing ? "alert" : undefined}
            >
              {NOT_IN_STAMBOKEN_TEXT}
            </p>
            {missing && onAddRabbit && (
              <button
                type="button"
                className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                onClick={onAddRabbit}
              >
                Lägg till från intyget
              </button>
            )}
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
            <label className={styles.label}>
              Foto av överlåtelsebeviset eller intyget (om du har)
              <input
                type="file"
                accept="image/*,.heic,.pdf"
                disabled={busy}
                onChange={(e) => {
                  pick(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </label>
            {photo.status === "skickar" && (
              <LinearProgress aria-label="Fotot laddas upp" />
            )}
            {photo.status === "fel" && (
              <p className={styles.errorText} role="alert">
                {photo.error}
              </p>
            )}
            {photo.status === "klar" && (
              <>
                <p className={styles.meta} role="status">
                  Fotot är uppladdat.
                </p>
                <div
                  className={styles.choices}
                  role="radiogroup"
                  aria-label="Vad visar fotot?"
                >
                  <label className={styles.choice}>
                    <input
                      type="radio"
                      name="photo-type"
                      checked={docType === "bevis"}
                      onChange={() => setDocType("bevis")}
                    />
                    <span>Överlåtelsebevis</span>
                  </label>
                  <label className={styles.choice}>
                    <input
                      type="radio"
                      name="photo-type"
                      checked={docType === "intyg"}
                      onChange={() => setDocType("intyg")}
                    />
                    <span>Intyg</span>
                  </label>
                </div>
              </>
            )}
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
              disabled={busy || photo.status === "skickar"}
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
