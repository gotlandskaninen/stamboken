import type { GeneticPriority } from "@/redux/api/apiSlice";
import { decimal } from "@/lib/genetics";
import { translateReasons } from "@/utils/translateReasons";

export const PRIORITY_ORDER: Record<GeneticPriority["priority"], number> = {
  critical: 0,
  important: 1,
  normal: 2,
};

export const PRIORITY_LABEL: Record<GeneticPriority["priority"], string> = {
  critical: "Högsta",
  important: "Hög",
  normal: "Övriga",
};

export const sexLabel = (sex?: string | null) =>
  sex === "female" ? "Hona" : sex === "male" ? "Hane" : "Okänt";

/** The rows grouped per besättning within each level, so Högsta comes first and each herd's rabbits together. */
export const byHerd = (rows: GeneticPriority[]) =>
  [...rows].sort(
    (a, b) =>
      PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority] ||
      (a.herd ?? "").localeCompare(b.herd ?? "", "sv"),
  );

// Mirrors csv_safe (app/utils/csv_safe.py): a cell that starts like a formula gets a leading space.
const FORMULA_PREFIXES = ["=", "+", "-", "@", "\t", "\r"];
export function csvSafe(value: unknown): string {
  if (!value) return "";
  const s = String(value);
  return FORMULA_PREFIXES.includes(s[0]) ? ` ${s}` : s;
}

const HEADERS = [
  "Individnummer",
  "Namn",
  "Besättning",
  "Kön",
  "Född",
  "Avelsprioritet",
  "Ovanliga gener (0–100)",
  "Unika gener (%)",
  "Skäl",
];

/** The rows as CSV for Excel: BOM, semicolons, every cell quoted and made formula-safe. */
export function prioritiesCsv(rows: GeneticPriority[]): string {
  const lines = rows.map((r) => [
    r.individual_id,
    r.name,
    r.herd,
    sexLabel(r.sex),
    r.birth_date,
    PRIORITY_LABEL[r.priority],
    decimal(r.genetic_value_score),
    decimal(r.genome_uniqueness * 100, 1),
    translateReasons(r.reasons, r.individual_id).join("; "),
  ]);
  return (
    "﻿" +
    [HEADERS, ...lines]
      .map((cells) =>
        cells.map((c) => `"${csvSafe(c).replace(/"/g, '""')}"`).join(";"),
      )
      .join("\r\n")
  );
}

export function downloadCsv(fileName: string, csv: string) {
  const url = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  a.click();
  URL.revokeObjectURL(url);
}
