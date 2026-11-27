"use client";

import { useId } from "react";
import {
  takeRead,
  type CertForm,
  type Grandparents,
  type Proposal,
  type Reconciliation,
  type RowKey,
  type RowStatus,
  type SaveMode,
} from "../lib";
import styles from "../inkorg.module.css";

const ROWS: [RowKey, string][] = [
  ["individual", "Individnummer i Stamboken"],
  ["paper_number", "Individnummer på pappret"],
  ["paper_certificate", "Intygsnummer"],
  ["name", "Namn"],
  ["sex", "Kön"],
  ["birth_date", "Födelsedatum"],
  ["color", "Färg"],
  ["litter_size", "Antal födda"],
  ["litter_size6w", "Levande efter 6 veckor"],
  ["mother", "Mor"],
  ["morfar", "Morfar"],
  ["mormor", "Mormor"],
  ["father", "Far"],
  ["farfar", "Farfar"],
  ["farmor", "Farmor"],
];
const GRANDPARENTS = new Set<RowKey>(["morfar", "mormor", "farfar", "farmor"]);
// The fields that had an example number before the table (not the grandparents: it would read as theirs).
const EXAMPLE = new Set<RowKey>([
  "individual",
  "paper_number",
  "mother",
  "father",
]);
// What saving needs in each mode, as the form has always asked for it.
const REQUIRED: Record<SaveMode, RowKey[]> = {
  pappersintyg: ["individual", "paper_number", "paper_certificate"],
  ny_kanin: [
    "paper_number",
    "paper_certificate",
    "birth_date",
    "mother",
    "father",
  ],
};
const WORD: Record<RowStatus, string> = {
  stammer: "stämmer",
  skiljer: "skiljer sig",
  osaker: "osäker",
  ingen: "inget att jämföra",
};
const SEX: Record<string, string> = { female: "Hona", male: "Hane" };

export const rowKeys = (mode: SaveMode) =>
  ROWS.filter(([key]) => mode === "pappersintyg" || key !== "individual");

/** "9 stämmer · 2 osäkra · 1 skiljer sig · 2 utan jämförelse" */
export function summaryText(answer: Reconciliation, mode: SaveMode) {
  const n: Record<RowStatus, number> = {
    stammer: 0,
    osaker: 0,
    skiljer: 0,
    ingen: 0,
  };
  for (const [key] of rowKeys(mode)) {
    const status = answer.rows[key]?.status;
    if (status) n[status]++;
  }
  return [
    `${n.stammer} stämmer`,
    `${n.osaker} ${n.osaker === 1 ? "osäker" : "osäkra"}`,
    `${n.skiljer} skiljer sig`,
    `${n.ingen} utan jämförelse`,
  ].join(" · ");
}

const shown = (key: RowKey, value: string | number | null | undefined) =>
  value === null || value === undefined
    ? "–"
    : key === "sex"
      ? (SEX[value] ?? String(value))
      : String(value);

/**
 * The queue's certificate form as a table: per row what the image reading
 * read (Inläst), what the handler types off the paper (Pappret), the
 * registry's value and a status in words, recomputed by the caller as she
 * types. A number not in the registry offers those one character off, and an
 * osäker row offers to take what was read. In a narrow pane each row is a card.
 */
export function ReconcileTable({
  mode,
  values,
  onChange,
  proposal,
  answer,
  colors,
  errors,
}: {
  mode: SaveMode;
  values: CertForm & Grandparents;
  onChange: (key: RowKey, value: string) => void;
  proposal: Proposal | null;
  answer: Reconciliation | null;
  colors: string[];
  errors: Partial<Record<keyof CertForm, string>>;
}) {
  const id = useId();

  const field = (key: RowKey, label: string) => {
    const error = errors[key as keyof CertForm];
    const props = {
      id: `${id}-${key}`,
      className: styles.reconcileInput,
      value: values[key],
      required: REQUIRED[mode].includes(key),
      "aria-invalid": error ? true : undefined,
      "aria-describedby": error ? `${id}-${key}-error` : undefined,
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
        onChange(key, e.target.value),
    };
    const input =
      key === "sex" || (key === "color" && colors.length > 0) ? (
        <select {...props}>
          <option value="">Inte angivet</option>
          {key === "sex"
            ? Object.entries(SEX).map(([value, word]) => (
                <option key={value} value={value}>
                  {word}
                </option>
              ))
            : colors.map((c) => (
                <option key={c} value={c}>
                  {c}
                </option>
              ))}
        </select>
      ) : (
        <input
          {...props}
          type={
            key === "birth_date"
              ? "date"
              : key === "litter_size" || key === "litter_size6w"
                ? "number"
                : "text"
          }
          min={key === "litter_size" || key === "litter_size6w" ? 1 : undefined}
          maxLength={
            key === "paper_certificate" ? 20 : key === "name" ? 50 : undefined
          }
          placeholder={EXAMPLE.has(key) ? "G1274-2512" : undefined}
          autoComplete="off"
          spellCheck={false}
        />
      );
    return (
      <>
        {input}
        {key === "litter_size6w" && (
          <span className={styles.reconcileHint}>
            Står inte alltid på intyget.
          </span>
        )}
        {error && (
          <span id={`${id}-${key}-error`} className={styles.error}>
            {error}
          </span>
        )}
      </>
    );
  };

  return (
    <div className={styles.reconcile}>
      <p className={styles.muted}>
        Inläst är det bildtolkningen läste. Pappret skriver du av från fotot.
        Registret är det Stamboken har.
      </p>
      {answer && (
        <p className={styles.reconcileSummary} aria-live="polite">
          {summaryText(answer, mode)}
        </p>
      )}
      <div className={styles.reconcileFrame}>
        <table>
          <thead>
            <tr>
              <th scope="col">Rad</th>
              <th scope="col">Inläst</th>
              <th scope="col">Pappret</th>
              <th scope="col">Registret</th>
              <th scope="col">Status</th>
            </tr>
          </thead>
          <tbody>
            {rowKeys(mode).map(([key, label]) => {
              const row = answer?.rows[key];
              const read = proposal?.fields[key]?.read;
              const take =
                row?.status === "osaker" && read
                  ? takeRead(key, read, colors)
                  : null;
              const gp = GRANDPARENTS.has(key) || undefined;
              return [
                <tr
                  key={key}
                  className={styles.reconcileRow}
                  data-grandparent={gp}
                >
                  <th scope="row">
                    <label htmlFor={`${id}-${key}`}>{label}</label>
                  </th>
                  <td className={styles.reconcileRead} data-label="Inläst">
                    {read || "–"}
                  </td>
                  <td className={styles.reconcilePaper}>{field(key, label)}</td>
                  <td
                    className={styles.reconcileRegistry}
                    data-label="Registret"
                  >
                    {shown(key, row?.registry)}
                  </td>
                  <td className={styles.reconcileStatus}>
                    {row && (
                      <span className={styles.chip} data-status={row.status}>
                        {WORD[row.status]}
                      </span>
                    )}
                    {take !== null && (
                      <button
                        type="button"
                        className="sb-btn sb-btn-secondary sb-btn-sm"
                        aria-label={`Ta inläst: ${label}`}
                        onClick={() => onChange(key, take)}
                      >
                        Ta inläst
                      </button>
                    )}
                  </td>
                </tr>,
                row?.near?.length ? (
                  <tr
                    key={`${key}-near`}
                    className={styles.nearRow}
                    data-grandparent={gp}
                  >
                    <td colSpan={5}>
                      <div className={styles.near}>
                        <span>Menar du:</span>
                        {row.near.map((r) => (
                          <button
                            key={r.number}
                            type="button"
                            className="sb-btn sb-btn-secondary sb-btn-sm"
                            onClick={() => onChange(key, r.number)}
                          >
                            {[
                              r.number,
                              r.name,
                              r.sex && `(${shown("sex", r.sex).toLowerCase()})`,
                            ]
                              .filter(Boolean)
                              .join(" ")}
                          </button>
                        ))}
                      </div>
                    </td>
                  </tr>
                ) : null,
              ];
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
