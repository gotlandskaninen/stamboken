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
  PURCHASE_SENT_TEXT,
  todayStockholm,
  type PurchaseBody,
  type PurchaseNotice,
  type PurchasePhotosBody,
} from "./lib";
import { HerdPicker } from "./SoldDialog";
import { MAX_BYTES } from "./AddRabbit";
import { prepare } from "../inskick/ny/prepare";
import { useLeaveWarning } from "./useLeaveWarning";
import styles from "./arsrapport.module.css";

type Photo = {
  status: "tom" | "skickar" | "klar" | "fel";
  document_id?: number;
  error?: string;
  docType?: "bevis" | "intyg"; // what the photo shows, chosen once it is uploaded
};
const EMPTY: Photo = { status: "tom" };
const PHOTO_TYPE_TEXT = "Välj om fotot visar överlåtelsebeviset eller intyget.";
// S7: a number Stamboken lacks. The buyer sends the photos; the genebank manager registers the rabbit.
export const NOT_IN_STAMBOKEN_TEXT =
  "Kaninen finns inte i Stamboken än. Skicka foto av intyget, och av överlåtelsebeviset om du har det. Genbanksansvarig registrerar kaninen och för över den till dig.";
export const PHOTOS_SENT_TEXT =
  "Fotona är skickade till genbanksansvarig. Kaninen kommer in i din besättning när den är registrerad och överförd.";
const PHOTO_REQUIRED_TEXT = "Ladda upp ett foto av intyget.";
// The number first: a typo is corrected before any photo is asked for.
export const notInStamboken = (number: string) =>
  `${number} finns inte i Stamboken. Stämmer numret?`;

type Upload = (
  data: FormData,
  purpose: "kop" | "inskick",
) => Promise<ActionResult<{ item_id: number; document_id: number }>>; // the report's photo upload (4b)

interface Props {
  open: boolean;
  year: number;
  genebankId: number;
  ownHerd: string; // the buyer's herd: not a seller
  loadHerds: typeof getGenebankHerds; // as SoldDialog gets it; the link's own list behind the link
  send: (body: PurchaseBody) => Promise<ActionResult<PurchaseNotice>>;
  sendPhotos: (
    body: PurchasePhotosBody,
  ) => Promise<ActionResult<PurchaseNotice>>;
  upload: Upload;
  onSent: () => void;
  onClose: () => void;
}

// One photo through the report's upload, and what it shows.
function PhotoField({
  label,
  typeLabel,
  purpose,
  upload,
  disabled,
  photo,
  onChange,
}: {
  label: string;
  typeLabel: string;
  purpose: "kop" | "inskick";
  upload: Upload;
  disabled: boolean;
  photo: Photo;
  onChange: (photo: Photo) => void;
}) {
  const attempt = React.useRef(0); // a newer photo's upload drops an earlier one's answer
  const name = React.useId();

  const pick = async (file: File | undefined) => {
    if (!file) return;
    const mine = ++attempt.current;
    onChange({ status: "skickar" });
    let next: Photo;
    try {
      const prepared = await prepare(file);
      if (prepared.size > MAX_BYTES)
        next = { status: "fel", error: "Filen är för stor. Max 10 MB." };
      else {
        const data = new FormData();
        data.set("file", prepared);
        const res = await upload(data, purpose);
        next = res.ok
          ? { status: "klar", document_id: res.data.document_id }
          : { status: "fel", error: res.problem.detail };
      }
    } catch {
      next = { status: "fel", error: "Uppladdningen avbröts. Försök igen." };
    }
    if (attempt.current === mine) onChange(next);
  };

  return (
    <>
      <label className={styles.label}>
        {label}
        <input
          type="file"
          accept="image/*,.heic,.pdf"
          disabled={disabled}
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
            aria-label={typeLabel}
          >
            <label className={styles.choice}>
              <input
                type="radio"
                name={name}
                checked={photo.docType === "bevis"}
                onChange={() => onChange({ ...photo, docType: "bevis" })}
              />
              <span>Överlåtelsebevis</span>
            </label>
            <label className={styles.choice}>
              <input
                type="radio"
                name={name}
                checked={photo.docType === "intyg"}
                onChange={() => onChange({ ...photo, docType: "intyg" })}
              />
              <span>Intyg</span>
            </label>
          </div>
        </>
      )}
    </>
  );
}

// "Anmäl ett köp" (4a Task 5): a rabbit bought during the year that Stamboken
// has not moved into the herd. The genebank manager registers the purchase.
function Body({
  year,
  genebankId,
  ownHerd,
  loadHerds,
  send,
  sendPhotos,
  upload,
  onSent,
  onClose,
}: Props) {
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [number, setNumber] = React.useState("");
  const numberField = React.useRef<HTMLInputElement>(null);
  const [outside, setOutside] = React.useState(false);
  const [code, setCode] = React.useState("");
  const [date, setDate] = React.useState("");
  const [tried, setTried] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [refused, setRefused] = React.useState<string | null>(null);
  const [missing, setMissing] = React.useState(false); // the number is not in Stamboken: photos to the queue (S7)
  const [sent, setSent] = React.useState<string | null>(null); // what was sent, in words
  const [photo, setPhoto] = React.useState<Photo>(EMPTY); // the notice's
  const [photos, setPhotos] = React.useState<Photo[]>([EMPTY, EMPTY]); // the certificate's and the proof's
  const setPhotoAt = (i: number) => (p: Photo) =>
    setPhotos((all) => all.map((old, k) => (k === i ? p : old)));
  const today = todayStockholm();
  const last = `${year}-12-31` < today ? `${year}-12-31` : today;
  const uploaded = photos.filter((p) => p.status === "klar");
  const uploading = [photo, ...photos].some((p) => p.status === "skickar");
  // an uploaded photo is held, not sent, until the notice is
  const unsent = !sent && [photo, ...photos].some((p) => p.status === "klar");
  const [asking, setAsking] = React.useState(false);
  useLeaveWarning(unsent);
  const close = () => (unsent ? setAsking(true) : onClose());
  const problem =
    (!number.trim() && "Skriv kaninens nummer.") ||
    (!outside &&
      !code &&
      "Välj en besättning i genbanken, eller Utanför genbanken.") ||
    (!date && "Välj datum för köpet.") ||
    (missing && uploaded.length === 0 && PHOTO_REQUIRED_TEXT) ||
    (missing && uploaded.some((p) => !p.docType) && PHOTO_TYPE_TEXT) ||
    (!missing &&
      photo.status === "klar" &&
      !photo.docType &&
      PHOTO_TYPE_TEXT) ||
    null;

  const submit = async () => {
    setTried(true);
    if (problem || busy || uploading) return;
    setBusy(true);
    setRefused(null);
    const fields = {
      number: number.trim(),
      from_herd: outside ? "utanfor" : code,
      date,
    };
    try {
      if (missing) {
        const res = await sendPhotos({
          ...fields,
          documents: uploaded.map((p) => ({
            id: p.document_id!,
            doc_type: p.docType!,
          })),
        });
        if (res.ok) {
          setSent(PHOTOS_SENT_TEXT);
          onSent();
        } else if (res.problem.extensions?.field === "photo")
          setPhotos([{ status: "fel", error: res.problem.detail }, EMPTY]); // chosen again
        else setRefused(res.problem.detail || res.problem.title);
        return;
      }
      const res = await send({
        ...fields,
        ...(photo.status === "klar" && photo.docType
          ? { document_id: photo.document_id, doc_type: photo.docType }
          : {}),
      });
      if (res.ok) {
        setSent(PURCHASE_SENT_TEXT);
        onSent();
      } else if (res.problem.extensions?.code === "inte_i_stamboken") {
        setMissing(true);
        setTried(false); // the photos are asked for, not yet missing
        if (photo.status === "klar") {
          // the photo already uploaded is sent with the others, with what it shows, not left held
          setPhotos((all) => {
            const free = all.findIndex((p) => p.status === "tom");
            return all.map((p, k) => (k === free ? photo : p));
          });
          setPhoto(EMPTY);
        }
      } else if (res.problem.extensions?.field === "photo")
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
      onClose={busy ? undefined : close}
      fullScreen={mobile}
      fullWidth
      maxWidth="sm"
      aria-labelledby="purchase-title"
    >
      <DialogTitle id="purchase-title" sx={{ pr: 6 }}>
        Anmäl ett köp
        <IconButton
          aria-label="Stäng"
          onClick={close}
          disabled={busy}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers={mobile} className={styles.detail}>
        {asking ? (
          <p role="alertdialog" aria-label="Anmälan är inte skickad">
            Anmälan är inte skickad. Stäng ändå?
          </p>
        ) : sent ? (
          <p role="status">{sent}</p>
        ) : (
          <>
            <label className={styles.label}>
              Kaninens nummer
              <input
                ref={numberField}
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
            {missing ? (
              // Not "Lägg till från intyget": a rabbit of another herd's litter is registered for that herd, never
              // by its buyer. Its photos go to the queue as an upload, and the manager registers and transfers it.
              <>
                <p role="status">{notInStamboken(number.trim())}</p>
                <button
                  type="button"
                  className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                  onClick={() => {
                    setMissing(false);
                    numberField.current?.focus();
                  }}
                >
                  Ändra numret
                </button>
                <p className={styles.meta}>{NOT_IN_STAMBOKEN_TEXT}</p>
                <PhotoField
                  label="Foto 1"
                  typeLabel="Vad visar foto 1?"
                  purpose="inskick"
                  upload={upload}
                  disabled={busy}
                  photo={photos[0]}
                  onChange={setPhotoAt(0)}
                />
                {/* the second once the first is uploaded, and while it holds a photo */}
                {(photos[0].status === "klar" ||
                  photos[1].status !== "tom") && (
                  <PhotoField
                    label="Foto 2 (om du har)"
                    typeLabel="Vad visar foto 2?"
                    purpose="inskick"
                    upload={upload}
                    disabled={busy}
                    photo={photos[1]}
                    onChange={setPhotoAt(1)}
                  />
                )}
              </>
            ) : (
              <PhotoField
                label="Foto av överlåtelsebeviset eller intyget (om du har)"
                typeLabel="Vad visar fotot?"
                purpose="kop"
                upload={upload}
                disabled={busy}
                photo={photo}
                onChange={setPhoto}
              />
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
        {asking ? (
          <>
            <button
              type="button"
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
              onClick={() => setAsking(false)}
            >
              Fortsätt
            </button>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              onClick={onClose}
            >
              Stäng
            </button>
          </>
        ) : sent ? (
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
              onClick={close}
              disabled={busy}
            >
              Avbryt
            </button>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              onClick={submit}
              disabled={busy || uploading}
            >
              {busy
                ? "Skickar…"
                : missing
                  ? "Skicka till genbanksansvarig"
                  : "Skicka anmälan"}
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
