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
import { MONTHS, type SaldState } from "./lib";
import styles from "./arsrapport.module.css";

interface Props {
  open: boolean;
  number: string;
  year: number;
  herds: string[];
  breed: string; // lower case, as ORDLISTA writes breeds
  existing: SaldState | null; // a saved sale: its buyer fields start empty (Task 6)
  onSave: (s: SaldState) => void;
  onClose: () => void;
}

// The buyer outside the genebank is held in memory by the caller and never
// reaches the draft or localStorage.
function Body({
  number,
  year,
  herds,
  breed,
  existing,
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
  const [name, setName] = React.useState(existing?.kopare?.name ?? "");
  const [town, setTown] = React.useState(existing?.kopare?.town ?? "");
  const [tried, setTried] = React.useState(false);

  const clean = code.trim().toUpperCase();
  const known = herds.includes(clean);
  const buyerHalf = !!name.trim() !== !!town.trim();
  const buyerMissing = outside && !existing && !(name.trim() && town.trim());
  const problem =
    (!outside &&
      !known &&
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
      till: outside ? "utanfor" : clean,
      ar,
      manad,
      dag: dag ? Number(dag) : null,
      kopare:
        outside && name.trim() && town.trim()
          ? { name: name.trim(), town: town.trim() }
          : null,
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
          <>
            <label className={styles.label}>
              Köparens besättningsnummer
              <input
                className={styles.field}
                style={{ width: "100%", boxSizing: "border-box" }}
                autoCapitalize="characters"
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </label>
            {clean !== "" && (
              <p className={styles.meta} role="status">
                {known
                  ? `${clean} finns, ${breed}`
                  : `${clean} finns inte i genbanken`}
              </p>
            )}
          </>
        )}
        {outside && (
          <>
            <label className={styles.label}>
              Köparens namn
              <input
                className={styles.field}
                style={{ width: "100%", boxSizing: "border-box" }}
                maxLength={200}
                autoComplete="off"
                value={name}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label className={styles.label}>
              Köparens ort
              <input
                className={styles.field}
                style={{ width: "100%", boxSizing: "border-box" }}
                maxLength={200}
                autoComplete="off"
                value={town}
                onChange={(e) => setTown(e.target.value)}
              />
            </label>
            {existing && (
              <p className={styles.meta}>
                Köparens uppgifter sparas inte i rapporten. Lämna fälten tomma
                om köparen är rätt, och fyll i dem om du vill rätta köparen.
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
