"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import styles from "../../arsrapport.module.css";

// The masthead's choice of genebank and round. The round is in the path, so a plain GET form cannot change it.
export function StatusSwitch({
  year,
  years,
  genebankId,
  genebanks,
}: {
  year: number;
  years: number[];
  genebankId: number;
  genebanks: { id: number; name: string }[];
}) {
  const router = useRouter();
  const [chosen, setChosen] = useState({ year, genebankId });
  if (genebanks.length < 2 && years.length < 2) return null;
  return (
    <form
      className={styles.switch}
      onSubmit={(e) => {
        e.preventDefault();
        router.push(
          `/stamboken/arsrapport/status/${chosen.year}?genebank_id=${chosen.genebankId}`,
        );
      }}
    >
      {genebanks.length > 1 && (
        <label>
          Genbank
          <select
            className={`sb-input ${styles.field}`}
            value={chosen.genebankId}
            onChange={(e) =>
              setChosen({ ...chosen, genebankId: Number(e.target.value) })
            }
          >
            {genebanks.map((g) => (
              <option key={g.id} value={g.id}>
                {g.name}
              </option>
            ))}
          </select>
        </label>
      )}
      {years.length > 1 && (
        <label>
          Runda
          <select
            className={`sb-input ${styles.field}`}
            value={chosen.year}
            onChange={(e) =>
              setChosen({ ...chosen, year: Number(e.target.value) })
            }
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        </label>
      )}
      <button
        type="submit"
        className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
      >
        Visa
      </button>
    </form>
  );
}
