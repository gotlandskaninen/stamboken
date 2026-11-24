"use client";

import React from "react";
import type { RabbitView } from "./lib";
import styles from "./arsrapport.module.css";

// The empty entry row of the paper form: "G9002-" is fixed text, the person
// types the rest and presses Enter. A hit becomes an ordinary rabbit row; a
// miss says so and keeps the focus and the text.
export function NumberRow({
  herd,
  year,
  rabbits,
  entered,
  onPick,
  onReveal,
}: {
  herd: string;
  year: number;
  rabbits: RabbitView[];
  entered: number[];
  onPick: (id: number) => void;
  onReveal: (id: number) => void; // show the row (clears the filter)
}) {
  const [value, setValue] = React.useState("");
  const [problem, setProblem] = React.useState<React.ReactNode>(null);
  const ref = React.useRef<HTMLInputElement>(null);

  const pick = () => {
    const typed = value.trim().toUpperCase();
    if (!typed) return;
    // a full number is taken as written (the register selects by holding, so
    // a rabbit numbered in another herd is valid); a bare part gets the prefix
    const number = typed.includes("-") ? typed : `${herd}-${typed}`;
    const hit = rabbits.find((r) => r.number.toUpperCase() === number);
    if (!hit) {
      setProblem(
        `${number} finns inte bland kaninerna i ${herd} den 31 december ${year}.`,
      );
      ref.current?.select();
    } else if (entered.includes(hit.id)) {
      setProblem(
        <>
          Redan inmatad på{" "}
          <a
            href={`#rabbit-${hit.id}`}
            onClick={(e) => {
              e.preventDefault();
              onReveal(hit.id);
            }}
          >
            rad {entered.indexOf(hit.id) + 1}
          </a>
        </>,
      );
      ref.current?.select();
    } else if (hit.state !== "att_valja") {
      setProblem(
        `${hit.number} är redan rapporterad eller flyttad och räknas inte med här.`,
      );
      ref.current?.select();
    } else {
      setProblem(null);
      setValue("");
      onPick(hit.id);
    }
  };

  return (
    <div className={styles.numberRow}>
      <label className={styles.label} htmlFor="paper-number">
        Nästa kanin på blanketten
      </label>
      <div className={styles.prefixed}>
        <span aria-hidden="true">{herd}-</span>
        <input
          ref={ref}
          id="paper-number"
          data-paper-field="number"
          aria-label={`Nummer efter ${herd}-`}
          aria-describedby={
            problem
              ? "paper-number-help paper-number-problem"
              : "paper-number-help"
          }
          inputMode="numeric"
          autoComplete="off"
          value={value}
          onChange={(e) => {
            setValue(e.target.value);
            setProblem(null);
          }}
          onKeyDown={(e) => {
            if (e.key !== "Enter") return;
            e.preventDefault();
            pick();
          }}
        />
      </div>
      <p id="paper-number-help" className={styles.meta}>
        Enter går vidare. När kaninens val har fokus: 1 Finns kvar, 2 Död, 3
        Såld.
      </p>
      {problem && (
        <p id="paper-number-problem" className={styles.errorText} role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}
