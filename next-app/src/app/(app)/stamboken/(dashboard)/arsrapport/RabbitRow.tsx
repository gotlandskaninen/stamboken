"use client";

import React from "react";
import {
  EJ_VAGD_REASONS,
  EMPTY_ENTRY,
  HULL_LABELS,
  MONTHS,
  PENDING_SALE_TEXT,
  ageText,
  fmtDate,
  kgText,
  parseWeight,
  sexText,
  type Entry,
  type Hull,
  type RabbitView,
  type Val,
} from "./lib";
import styles from "./arsrapport.module.css";

export interface RabbitRowProps {
  r: RabbitView;
  entry: Entry | undefined;
  ending: boolean;
  year: number;
  canSell: boolean;
  // The row's sale is, or becomes on Skicka, a proposal for the genebank manager (5.9).
  proposal?: boolean;
  done: boolean;
  error?: string;
  onChange: (id: number, patch: Partial<Entry>) => void;
  onSell: (id: number) => void;
  onNextWeight: (id: number) => void;
  // Paper entry: a fourth choice for a rabbit the form does not mention.
  paper?: boolean;
}

const CHOICES: { val: Val; label: string }[] = [
  { val: "kvar", label: "Finns kvar" },
  { val: "dod", label: "Död" },
  { val: "sald", label: "Såld" },
];

function saleText(e: Entry): string {
  const s = e.sald!;
  const to = s.till === "utanfor" ? "utanför genbanken" : s.till;
  const when =
    s.manad === null
      ? String(s.ar)
      : `${s.dag ? s.dag + " " : ""}${MONTHS[s.manad - 1]} ${s.ar}`;
  return `Såld till ${to}, ${when}`;
}

function RabbitRowImpl({
  r,
  entry,
  ending,
  year,
  canSell,
  proposal = false,
  done,
  error,
  onChange,
  onSell,
  onNextWeight,
  paper = false,
}: RabbitRowProps) {
  const e = entry ?? EMPTY_ENTRY;
  const [viktOk, setViktOk] = React.useState<string | null>(null);
  const [annat, setAnnat] = React.useState(
    !!e.ej_vagd && !(EJ_VAGD_REASONS as readonly string[]).includes(e.ej_vagd),
  );
  const [prevVikt, setPrevVikt] = React.useState(""); // the weight Ej vägd cleared: back when it is turned off
  const errId = `err-${r.id}`;
  const set = (patch: Partial<Entry>) => onChange(r.id, patch);

  const choose = (val: Val) => {
    if (val === "sald") return onSell(r.id); // a dialog; the choice is made when it is saved
    set({
      val,
      dod:
        val === "dod" && !e.dod
          ? { ar: year, manad: null, dag: null, slaktad: false, anteckning: "" }
          : e.dod,
    });
  };

  const w = parseWeight(e.vikt);
  const kvarOpen = e.val === "kvar";
  const quiet = r.state !== "att_valja" && !e.val;
  const meta = [
    paper ? null : sexText(r),
    r.castrated ? "kastrerad" : null,
    paper ? null : r.color,
    ageText(r, year),
    r.last_reported
      ? `senast rapporterad ${r.last_reported.slice(0, 4)}`
      : null,
  ]
    .filter(Boolean)
    .join(" · ");

  return (
    <fieldset
      id={`rabbit-${r.id}`}
      tabIndex={-1}
      className={`${styles.row} ${quiet ? styles.quiet : ""} ${error ? styles.rowError : ""}`}
      aria-describedby={error ? errId : undefined}
    >
      <legend>
        {paper && <span className={styles.meta}>{sexText(r)} </span>}
        <span className={styles.num}>{r.number}</span>{" "}
        <span className={styles.name}>{r.name}</span>
        {paper && r.color && <span className={styles.meta}> {r.color}</span>}
        {done && <span className={styles.klar}>✓ Klar</span>}
      </legend>
      <p className={styles.meta}>{meta}</p>
      {r.death_date && (
        <p className={styles.meta}>
          Dödsfall registrerat {fmtDate(r.death_date)}
        </p>
      )}

      {r.state === "redan_rapporterad" && !e.val && (
        <p>Redan rapporterad 31 december {year}</p>
      )}
      {r.state === "via_flytt" && !e.val && (
        <p>
          Flyttad {r.later ? fmtDate(r.later.date) : ""}, räknas via flytten
        </p>
      )}

      {(r.state === "att_valja" || e.val) && (
        <>
          {e.val === "ej_angiven" && !paper && <p>Ej angiven på blanketten</p>}
          <div className={styles.choices}>
            {(paper
              ? [
                  ...CHOICES,
                  {
                    val: "ej_angiven" as Val,
                    label: "Ej angiven på blanketten",
                  },
                ]
              : CHOICES
            ).map(({ val, label }) => {
              return (
                <label key={val} className={styles.choice}>
                  <input
                    type="radio"
                    name={`val-${r.id}`}
                    id={`val-${r.id}-${val}`}
                    data-paper-field="val"
                    value={val}
                    checked={e.val === val}
                    data-need={!e.val || undefined}
                    onChange={() => choose(val)}
                  />
                  <span>{label}</span>
                </label>
              );
            })}
          </div>
        </>
      )}

      {kvarOpen && (
        <div className={styles.detail}>
          <div className={styles.line}>
            <label className={styles.label} htmlFor={`vikt-${r.id}`}>
              Vikt
            </label>
            <input
              id={`vikt-${r.id}`}
              data-paper-field="vikt"
              className={`${styles.field} ${styles.weight}`}
              inputMode="decimal"
              data-need={
                (r.adult && !e.vikt.trim() && !e.ej_vagd?.trim()) || undefined
              }
              enterKeyHint="next"
              autoComplete="off"
              value={e.vikt}
              onChange={(ev) => set({ vikt: ev.target.value, ej_vagd: null })}
              onKeyDown={(ev) => {
                if (ev.key === "Enter") {
                  ev.preventDefault();
                  onNextWeight(r.id);
                }
              }}
            />
            <span aria-hidden="true">kg</span>
            <button
              type="button"
              id={`ejvagd-${r.id}`}
              data-paper-field="ej_vagd"
              className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
              aria-pressed={e.ej_vagd !== null}
              onClick={() => {
                setAnnat(false);
                if (e.ej_vagd === null) {
                  setPrevVikt(e.vikt);
                  set({ ej_vagd: "", vikt: "" });
                } else set({ ej_vagd: null, vikt: prevVikt });
              }}
            >
              Ej vägd
            </button>
          </div>
          {w.gramsHint !== null && (
            <p className={styles.note}>
              Menade du {kgText(w.gramsHint)} kg?
              <button
                type="button"
                className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                onClick={() => set({ vikt: kgText(w.gramsHint!) })}
              >
                Ja, {kgText(w.gramsHint)} kg
              </button>
            </p>
          )}
          {w.kg !== null && w.unusual && viktOk !== e.vikt && (
            <p className={styles.note}>
              Stämmer {kgText(w.kg)} kg?
              <button
                type="button"
                className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                onClick={() => setViktOk(e.vikt)}
              >
                Ja, det stämmer
              </button>
            </p>
          )}
          {e.ej_vagd !== null && (
            <div
              className={styles.grid2}
              role="group"
              aria-label="Varför vägdes den inte?"
            >
              {EJ_VAGD_REASONS.map((reason) => (
                <button
                  key={reason}
                  type="button"
                  className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                  aria-pressed={e.ej_vagd === reason}
                  onClick={() => {
                    setAnnat(false);
                    set({ ej_vagd: reason });
                  }}
                >
                  {reason}
                </button>
              ))}
              <button
                type="button"
                className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                aria-pressed={annat}
                onClick={() => {
                  setAnnat(true);
                  set({ ej_vagd: "" });
                }}
              >
                Annat …
              </button>
              {annat && (
                <input
                  className={styles.field}
                  aria-label="Annat skäl"
                  maxLength={200}
                  value={e.ej_vagd ?? ""}
                  onChange={(ev) => set({ ej_vagd: ev.target.value })}
                />
              )}
            </div>
          )}
          <div className={styles.line}>
            <label className={styles.label} htmlFor={`hull-${r.id}`}>
              Hull<span className={styles.optional}> (frivilligt)</span>
            </label>
            <select
              id={`hull-${r.id}`}
              data-paper-field="hull"
              className={`${styles.field} ${styles.hull}`}
              value={e.hull ?? ""}
              onChange={(ev) =>
                set({ hull: (ev.target.value || null) as Hull | null })
              }
            >
              <option value="">Ingen uppgift</option>
              {(Object.keys(HULL_LABELS) as Hull[]).map((h) => (
                <option key={h} value={h}>
                  {HULL_LABELS[h]}
                </option>
              ))}
            </select>
          </div>
        </div>
      )}

      {e.val === "dod" && e.dod && (
        <div className={styles.detail}>
          <div className={styles.grid2}>
            <label className={styles.label}>
              År
              <select
                className={`${styles.field} ${styles.btn}`}
                style={{ width: "100%" }}
                value={e.dod.ar}
                onChange={(ev) =>
                  set({ dod: { ...e.dod!, ar: Number(ev.target.value) } })
                }
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
                id={`month-${r.id}`}
                data-paper-field="month"
                className={styles.field}
                style={{ width: "100%" }}
                data-need={e.dod.manad === null || undefined}
                value={e.dod.manad ?? ""}
                onChange={(ev) =>
                  set({
                    dod: {
                      ...e.dod!,
                      manad: ev.target.value ? Number(ev.target.value) : null,
                    },
                  })
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
                id={`dag-${r.id}`}
                data-paper-field="day"
                className={styles.field}
                style={{ width: "100%", boxSizing: "border-box" }}
                inputMode="numeric"
                maxLength={2}
                value={e.dod.dag ?? ""}
                onChange={(ev) => {
                  const d = ev.target.value.replace(/\D/g, "");
                  set({ dod: { ...e.dod!, dag: d ? Number(d) : null } });
                }}
              />
            </label>
            <div role="group" aria-label="Slaktad">
              <span className={styles.label}>Slaktad</span>
              <div className={styles.choices}>
                {[true, false].map((v) => (
                  <label
                    key={String(v)}
                    className={`${styles.choice} ${styles.small}`}
                  >
                    <input
                      type="radio"
                      id={`slaktad-${r.id}-${v ? "ja" : "nej"}`}
                      data-paper-field="slaktad"
                      name={`slaktad-${r.id}`}
                      checked={e.dod!.slaktad === v}
                      onChange={() => set({ dod: { ...e.dod!, slaktad: v } })}
                    />
                    <span style={{ minHeight: 48 }}>{v ? "Ja" : "Nej"}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <label className={styles.label}>
            Anteckning
            <textarea
              id={`note-${r.id}`}
              data-paper-field="note"
              className={styles.field}
              maxLength={500}
              rows={2}
              value={e.dod.anteckning}
              onChange={(ev) =>
                set({ dod: { ...e.dod!, anteckning: ev.target.value } })
              }
            />
          </label>
        </div>
      )}

      {e.val === "sald" && e.sald && (
        <p className={styles.line} style={{ marginTop: 12 }}>
          <span>{saleText(e)}</span>
          {(canSell || proposal) && (
            <button
              type="button"
              className={`sb-btn sb-btn-ghost ${styles.btn}`}
              onClick={() => onSell(r.id)}
            >
              Ändra
            </button>
          )}
        </p>
      )}
      {e.val === "sald" && proposal && (
        <p className={styles.meta}>{PENDING_SALE_TEXT}</p>
      )}

      {error && (
        <p id={errId} className={styles.errorText}>
          {error}
        </p>
      )}
    </fieldset>
  );
}

export const RabbitRow = React.memo(RabbitRowImpl);
