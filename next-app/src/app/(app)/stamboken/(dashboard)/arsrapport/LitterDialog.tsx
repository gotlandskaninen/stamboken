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
import type { Father, Litter, LitterBody, RabbitView } from "./lib";
import { fmtDate } from "./lib";
import styles from "./arsrapport.module.css";

type Saved = { id: number; litters: Litter[] };
type Counts = { litter_size?: number; litter_size6w: number | null };

export const SAVED_NOTE =
  "Kullen är registrerad i Stamboken nu. Den finns kvar även om du drar tillbaka rapporten.";
const SAME_HINT =
  "En hona kan inte få två kullar så tätt. Stämmer inte datumet, ändra den befintliga kullen.";
const SIX_WEEKS_HINT =
  "Lämna tomt om kullen är yngre än 6 veckor, så räknar vi alla som levande tills du ändrar.";
const toInt = (v: string) => (/^\d+$/.test(v.trim()) ? Number(v) : null);

interface Props {
  open: boolean;
  year: number;
  mothers: RabbitView[]; // the herd's females on the report
  loadFathers: () => Promise<ActionResult<{ hanar: Father[] }>>;
  litters: Litter[]; // the year's litters: the one `samma_kull` names
  add: (body: LitterBody) => Promise<ActionResult<Saved>>;
  change: (id: number, body: Counts) => Promise<ActionResult<Saved>>;
  onSaved: (litters: Litter[]) => void;
  onClose: () => void;
}

function Body({
  year,
  mothers,
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
  const [error, setError] = React.useState<string | null>(null);
  const [same, setSame] = React.useState<number | null>(null); // samma_kull: the existing litter
  const [saved, setSaved] = React.useState(false);
  const [fathers, setFathers] = React.useState<
    Father[] | "fel" | null // null: still loading
  >(null);

  React.useEffect(() => {
    if (fathers !== null) return;
    let cancelled = false;
    loadFathers()
      .then((r) => {
        if (!cancelled) setFathers(r.ok ? r.data.hanar : "fel");
      })
      .catch(() => {
        if (!cancelled) setFathers("fel");
      });
    return () => {
      cancelled = true;
    };
  }, [fathers, loadFathers]);

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
  const fail = (detail: string) => setError(detail);

  const save = async () => {
    setTried(true);
    setError(null);
    if (problem || busy) return;
    setBusy(true);
    const res = await add({
      mother_id: Number(mother),
      father_id: father!.id,
      birth_date: born,
      litter_size: total!,
      litter_size6w: born6,
    });
    setBusy(false);
    if (res.ok) return done(res.data);
    const p = res.problem;
    if (p.status === 409 && p.extensions?.code === "samma_kull")
      return setSame(Number(p.extensions.breeding_id));
    fail(p.detail ?? "Kullen kunde inte sparas. Försök igen.");
  };

  const changeExisting = async () => {
    if (same === null || busy) return;
    setBusy(true);
    setError(null);
    const res = await change(same, {
      litter_size: total!,
      litter_size6w: born6,
    });
    setBusy(false);
    if (res.ok) return done(res.data);
    setSame(null);
    fail(res.problem.detail ?? "Kullen kunde inte ändras. Försök igen.");
  };

  const existing = same !== null ? litters.find((l) => l.id === same) : null;
  const motherNumber = mothers.find((m) => String(m.id) === mother)?.number;
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
                <option value="">Välj modern</option>
                {mothers.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name ? `${m.number} – ${m.name}` : m.number}
                  </option>
                ))}
              </select>
            </label>
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
            {fathers === "fel" && (
              <p className={styles.errorText} role="alert">
                Det gick inte att hämta hanarna.{" "}
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                  onClick={() => setFathers(null)}
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
              Ja, ändra den
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
  const [error, setError] = React.useState<string | null>(null);
  const n = toInt(count);
  const bad =
    n === null || (litter.litter_size !== null && n > litter.litter_size);

  const save = async () => {
    if (bad || busy) return;
    setBusy(true);
    setError(null);
    const res = await change(litter.id, { litter_size6w: n });
    setBusy(false);
    if (res.ok) {
      onSaved(res.data.litters);
      onClose();
    } else setError(res.problem.detail ?? "Antalet kunde inte sparas.");
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
