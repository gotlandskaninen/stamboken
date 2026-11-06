"use client";

import React from "react";
import {
  BAND_LABELS,
  BAND_REASON_TEXT,
  percent,
  type Band,
  type IndividualGeneticsData,
} from "@/lib/genetics";
import styles from "./GeneticsSummary.module.css";

const BAND_CLASS: Record<Band, string> = {
  A: "sb-badge sb-badge-skog",
  B: "sb-badge sb-badge-mossa",
  C: "sb-badge",
  D: `sb-badge ${styles.bandD}`,
  E: "sb-badge sb-badge-lera",
};

export function GeneticsSummary({ data }: { data: IndividualGeneticsData }) {
  const [open, setOpen] = React.useState(false);
  const panelId = React.useId();
  const reasonText =
    data.band_reason && data.band_reason !== "dead"
      ? BAND_REASON_TEXT[data.band_reason]
      : null;
  // Not for an animal sold outside the genebank: its reason already says why it has no band.
  const showNonMember =
    data.alive &&
    !data.in_reference &&
    data.mean_kinship != null &&
    (data.band_reason == null ||
      data.band_reason === "incomplete_pedigree" ||
      data.band_reason === "small_reference");
  return (
    <div className={styles.root}>
      <div className={styles.row}>
        {data.band && (
          <span className={BAND_CLASS[data.band]}>
            {data.band} · {BAND_LABELS[data.band]}
          </span>
        )}
        {reasonText && <span className="sb-meta">{reasonText}</span>}
        <span className="sb-meta">F {percent(data.inbreeding)}</span>
        {data.stale && <span className="sb-meta">Uppdateras…</span>}
        {data.alive && (
          <button
            type="button"
            className="sb-btn sb-btn-ghost sb-btn-sm"
            aria-controls={panelId}
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            Om genetiken
          </button>
        )}
      </div>
      {showNonMember && (
        <p className="sb-meta">
          Ingår inte i avelsstammen just nu – jämfört som om den gjorde det
        </p>
      )}
      {open && data.alive && (
        <div id={panelId} className={styles.panel}>
          {data.mean_kinship != null && <p>MK {percent(data.mean_kinship)}</p>}
          <p>
            {Math.round(data.pedigree_completeness * 100)} % känd stamtavla (5
            generationer)
          </p>
          <p>
            Avelsstammen just nu: {data.reference_size} djur. Bandet jämför med
            den.
          </p>
          {data.preliminary && (
            <p>Avelsstammen bestäms av en preliminär regel.</p>
          )}
        </div>
      )}
    </div>
  );
}
