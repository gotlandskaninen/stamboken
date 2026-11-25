"use client";

import React from "react";
import {
  Autocomplete,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import CloseIcon from "@mui/icons-material/Close";
import type { ActionResult } from "../inkorg/actions";
import type { Father, Litter, LitterBody } from "./lib";
import { fmtDate } from "./lib";
import { reportError } from "./reportError";
import styles from "./arsrapport.module.css";

type Saved = { id: number; litters: Litter[] };
type Counts = { litter_size?: number; litter_size6w: number | null };

export const SAVED_NOTE =
  "Kullen är registrerad i Stamboken nu. Den finns kvar även om du drar tillbaka rapporten.";
const SAME_HINT =
  "En hona kan inte få två kullar så tätt. Stämmer inte datumet, ändra den befintliga kullen.";
const SIX_WEEKS_HINT =
  "Lämna tomt om kullen är yngre än 6 veckor, så räknar vi alla som levande tills du ändrar.";
const FETCH_FAILED = "Det gick inte att nå servern. Försök igen.";

function useList(load: () => Promise<ActionResult<Father[]>>, what: string) {
  const [list, setList] = React.useState<
    Father[] | { error: React.ReactNode } | null
  >(null);
  const loader = React.useRef(load);
  React.useEffect(() => {
    loader.current = load;
  });
  React.useEffect(() => {
    if (list !== null) return;
    let cancelled = false;
    loader
      .current()
      .then((r) => {
        if (!cancelled)
          setList(
            r.ok ? r.data : { error: reportError(what, "hämtas", r.problem) },
          );
      })
      .catch(() => {
        if (!cancelled) setList({ error: FETCH_FAILED });
      });
    return () => {
      cancelled = true;
    };
  }, [list, what]);
  return [list, () => setList(null)] as const;
}

const toInt = (v: string) => (/^\d+$/.test(v.trim()) ? Number(v) : null);

interface Props {
  open: boolean;
  year: number;
  // the herd's does in the year, also those sold or dead since, and the genebank's males
  loadMothers: () => Promise<ActionResult<{ honor: Father[] }>>;
  loadFathers: () => Promise<ActionResult<{ hanar: Father[] }>>;
  litters: Litter[]; // the year's litters: the one `samma_kull` names
  add: (body: LitterBody) => Promise<ActionResult<Saved>>;
  change: (id: number, body: Counts) => Promise<ActionResult<Saved>>;
  onSaved: (litters: Litter[]) => void;
  onClose: () => void;
}

function Body({
  year,
  loadMothers,
  loadFathers,
  litters,
  add,
  change,
  onSaved,
  onClose,
}: Props) {
  const theme = useTheme();
  const mobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [mother, setMother] = React.useState("");
  const [father, setFather] = React.useState<Father | null>(null);
  const [born, setBorn] = React.useState("");
  const [size, setSize] = React.useState("");
  const [size6w, setSize6w] = React.useState("");
  const [tried, setTried] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<React.ReactNode>(null);
  const [same, setSame] = React.useState<number | null>(null); // samma_kull: the existing litter
  const [saved, setSaved] = React.useState(false);
  const [mothers, retryMothers] = useList(
    () => loadMothers().then((r) => (r.ok ? { ...r, data: r.data.honor } : r)),
    "Honorna",
  );
  const [fathers, retryFathers] = useList(
    () => loadFathers().then((r) => (r.ok ? { ...r, data: r.data.hanar } : r)),
    "Hanarna",
  );

  const born6 = size6w.trim() === "" ? null : toInt(size6w);
  const total = toInt(size);
  const problem =
    (!mother && "Välj modern.") ||
    (!father && "Välj fadern.") ||
    (!born && "Ange födelsedatum.") ||
    (born && (born < `${year}-01-01` || born > `${year}-12-31`)
      ? `Kullen måste vara född under ${year}.`
      : null) ||
    (total === null || total < 1 ? "Ange antal födda (minst 1)." : null) ||
    (size6w.trim() !== "" && born6 === null
      ? "Ange antal levande vid 6 veckor som ett heltal, eller lämna tomt."
      : null) ||
    (born6 !== null && total !== null && born6 > total
      ? "Antal levande vid 6 veckor kan inte vara fler än antal födda."
      : null) ||
    null;

  const done = (data: Saved) => {
    onSaved(data.litters);
    setSame(null);
    setSaved(true);
  };

  const save = async () => {
    setTried(true);
    setError(null);
    if (problem || busy) return;
    setBusy(true);
    let res;
    try {
      res = await add({
        mother_id: Number(mother),
        father_id: father!.id,
        birth_date: born,
        litter_size: total!,
        litter_size6w: born6,
      });
    } catch {
      return setError(FETCH_FAILED); // what was typed stays
    } finally {
      setBusy(false);
    }
    if (res.ok) return done(res.data);
    const p = res.problem;
    if (p.status === 409 && p.extensions?.code === "samma_kull")
      return setSame(Number(p.extensions.breeding_id));
    setError(reportError("Kullen", "sparas", p));
  };

  const changeExisting = async () => {
    if (same === null || busy) return;
    setBusy(true);
    setError(null);
    let res;
    try {
      res = await change(same, {
        litter_size: total!,
        litter_size6w: born6,
      });
    } catch {
      return setError(FETCH_FAILED); // the question stays, so "Ja, ändra den befintliga kullen" can be tried again
    } finally {
      setBusy(false);
    }
    if (res.ok) return done(res.data);
    setSame(null);
    setError(reportError("Kullen", "ändras", res.problem));
  };

  const existing = same !== null ? litters.find((l) => l.id === same) : null;
  const motherNumber = Array.isArray(mothers)
    ? mothers.find((m) => String(m.id) === mother)?.number
    : undefined;
  const fatherLabel = (f: Father) =>
    f.name ? `${f.number} – ${f.name}` : f.number;

  return (
    <Dialog
      open
      onClose={onClose}
      fullScreen={mobile}
      fullWidth
      maxWidth="sm"
      aria-labelledby="litter-title"
    >
      <DialogTitle id="litter-title" sx={{ pr: 6 }}>
        Lägg till kull
        <IconButton
          aria-label="Stäng"
          onClick={onClose}
          sx={{ position: "absolute", right: 8, top: 8 }}
        >
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers={mobile} className={styles.detail}>
        {saved ? (
          <p role="status">{SAVED_NOTE}</p>
        ) : same !== null ? (
          <>
            <p role="alert">
              Det finns redan en kull efter {motherNumber}
              {existing ? ` född ${fmtDate(existing.birth_date)}` : ""}. Är det
              samma kull?
            </p>
            <p className={styles.meta}>{SAME_HINT}</p>
          </>
        ) : (
          <>
            <label className={styles.label}>
              Mor
              <select
                className={styles.field}
                style={{ width: "100%" }}
                value={mother}
                onChange={(e) => setMother(e.target.value)}
              >
                <option value="">
                  {mothers === null ? "Hämtar honor …" : "Välj modern"}
                </option>
                {(Array.isArray(mothers) ? mothers : []).map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name ? `${m.number} – ${m.name}` : m.number}
                  </option>
                ))}
              </select>
            </label>
            {mothers && !Array.isArray(mothers) && (
              <p className={styles.errorText} role="alert">
                {mothers.error}{" "}
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                  onClick={retryMothers}
                >
                  Försök igen
                </button>
              </p>
            )}
            <Autocomplete
              options={Array.isArray(fathers) ? fathers : []}
              value={father}
              onChange={(_, f) => setFather(f)}
              getOptionLabel={fatherLabel}
              isOptionEqualToValue={(a, b) => a.id === b.id}
              loading={fathers === null}
              loadingText="Hämtar hanar …"
              noOptionsText="Ingen hane matchar"
              renderInput={(params) => <TextField {...params} label="Far" />}
            />
            {fathers && !Array.isArray(fathers) && (
              <p className={styles.errorText} role="alert">
                {fathers.error}{" "}
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                  onClick={retryFathers}
                >
                  Försök igen
                </button>
              </p>
            )}
            <div className={styles.grid2}>
              <label className={styles.label}>
                Född
                <input
                  type="date"
                  className={styles.field}
                  style={{ width: "100%", boxSizing: "border-box" }}
                  min={`${year}-01-01`}
                  max={`${year}-12-31`}
                  value={born}
                  onChange={(e) => setBorn(e.target.value)}
                />
              </label>
              <label className={styles.label}>
                Antal födda
                <input
                  className={styles.field}
                  style={{ width: "100%", boxSizing: "border-box" }}
                  inputMode="numeric"
                  value={size}
                  onChange={(e) => setSize(e.target.value.replace(/\D/g, ""))}
                />
              </label>
              <label className={styles.label}>
                Levande vid 6 veckor
                <input
                  className={styles.field}
                  style={{ width: "100%", boxSizing: "border-box" }}
                  inputMode="numeric"
                  aria-describedby="litter-6w-hint"
                  value={size6w}
                  onChange={(e) => setSize6w(e.target.value.replace(/\D/g, ""))}
                />
              </label>
            </div>
            <p id="litter-6w-hint" className={styles.meta}>
              {SIX_WEEKS_HINT}
            </p>
          </>
        )}
        {tried && problem && same === null && !saved && (
          <p className={styles.errorText} role="alert">
            {problem}
          </p>
        )}
        {error && (
          <p className={styles.errorText} role="alert">
            {error}
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
        {saved ? (
          <button
            type="button"
            className={`sb-btn ${styles.btn}`}
            onClick={onClose}
          >
            Klart
          </button>
        ) : same !== null ? (
          <>
            <button
              type="button"
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
              onClick={onClose}
            >
              Avbryt
            </button>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              disabled={busy}
              onClick={changeExisting}
            >
              Ja, ändra den befintliga kullen
            </button>
          </>
        ) : (
          <>
            <button
              type="button"
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
              onClick={onClose}
            >
              Avbryt
            </button>
            <button
              type="button"
              className={`sb-btn ${styles.btn}`}
              disabled={busy}
              onClick={save}
            >
              {busy ? "Sparar…" : "Spara kullen"}
            </button>
          </>
        )}
      </DialogActions>
    </Dialog>
  );
}

export function LitterDialog(props: Props) {
  return props.open ? <Body {...props} /> : null;
}

interface ConfirmProps {
  litter: Litter | null; // a preliminary litter; null keeps the dialog closed
  change: (id: number, body: Counts) => Promise<ActionResult<Saved>>;
  onSaved: (litters: Litter[]) => void;
  onClose: () => void;
}

// "Bekräfta antalet": the count alive at 6 weeks of a preliminary litter, as it is now or changed.
function ConfirmBody({
  litter,
  change,
  onSaved,
  onClose,
}: ConfirmProps & { litter: Litter }) {
  const [count, setCount] = React.useState(String(litter.litter_size6w ?? ""));
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<React.ReactNode>(null);
  const n = toInt(count);
  const bad =
    n === null || (litter.litter_size !== null && n > litter.litter_size);

  const save = async () => {
    if (bad || busy) return;
    setBusy(true);
    setError(null);
    let res;
    try {
      res = await change(litter.id, { litter_size6w: n });
    } catch {
      setError(FETCH_FAILED);
      return;
    } finally {
      setBusy(false);
    }
    if (res.ok) {
      onSaved(res.data.litters);
      onClose();
    } else setError(reportError("Antalet", "sparas", res.problem));
  };

  return (
    <Dialog
      open
      onClose={onClose}
      fullWidth
      maxWidth="xs"
      aria-labelledby="confirm-title"
    >
      <DialogTitle id="confirm-title">Bekräfta antalet</DialogTitle>
      <DialogContent className={styles.detail}>
        <p className={styles.meta}>
          Kullen född {fmtDate(litter.birth_date)}: {litter.litter_size} födda.
          Vi räknar just nu alla som levande.
        </p>
        <label className={styles.label}>
          Levande vid 6 veckor
          <input
            className={styles.field}
            style={{ width: "100%", boxSizing: "border-box" }}
            inputMode="numeric"
            value={count}
            onChange={(e) => setCount(e.target.value.replace(/\D/g, ""))}
          />
        </label>
        {n !== null &&
          litter.litter_size !== null &&
          n > litter.litter_size && (
            <p className={styles.errorText} role="alert">
              Antal levande vid 6 veckor kan inte vara fler än antal födda.
            </p>
          )}
        {error && (
          <p className={styles.errorText} role="alert">
            {error}
          </p>
        )}
      </DialogContent>
      <DialogActions>
        <button
          type="button"
          className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
          onClick={onClose}
        >
          Avbryt
        </button>
        <button
          type="button"
          className={`sb-btn ${styles.btn}`}
          disabled={bad || busy}
          onClick={save}
        >
          Bekräfta antalet
        </button>
      </DialogActions>
    </Dialog>
  );
}

export function ConfirmCountDialog(props: ConfirmProps) {
  return props.litter ? <ConfirmBody {...props} litter={props.litter} /> : null;
}
