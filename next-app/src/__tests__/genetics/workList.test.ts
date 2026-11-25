import { describe, it, expect } from "vitest";

import type { GeneticPriority } from "@/redux/api/apiSlice";
import { byHerd, csvSafe, prioritiesCsv } from "@/components/genetics/workList";

const row = (
  individual_id: string,
  priority: GeneticPriority["priority"],
  extra: Partial<GeneticPriority> = {},
): GeneticPriority => ({
  individual_id,
  priority,
  reasons: [],
  genetic_value_score: 91.4,
  genome_uniqueness: 0.103,
  name: "Doris",
  sex: "female",
  birth_date: "2024-05-01",
  herd: "G9001",
  ...extra,
});

const parse = (csv: string) =>
  csv
    .replace(/^﻿/, "")
    .split("\r\n")
    .map((line) => line.slice(1, -1).split('";"'));

describe("csvSafe", () => {
  it("mirrors the backend's csv_safe", () => {
    for (const risky of ["=1+1", "+46", "-2", "@SUM(A1)", "\tx", "\rx"]) {
      expect(csvSafe(risky)).toBe(` ${risky}`);
    }
    expect(csvSafe("G9001-2401")).toBe("G9001-2401");
    expect(csvSafe(null)).toBe("");
    expect(csvSafe("")).toBe("");
  });
});

describe("prioritiesCsv", () => {
  it("has a BOM, Swedish headers and one quoted row per given row", () => {
    const csv = prioritiesCsv([
      row("G9001-2401", "critical", {
        reasons: ["Sole active carrier of founder G9001-1101"],
      }),
      row("G9002-2402", "normal", { sex: null, name: null }),
    ]);
    expect(csv.startsWith("﻿")).toBe(true);
    const [headers, first, second, ...rest] = parse(csv);
    expect(headers).toEqual([
      "Individnummer",
      "Namn",
      "Besättning",
      "Kön",
      "Född",
      "Avelsprioritet",
      "Ovanliga gener (0–100)",
      "Unika gener (%)",
      "Skäl",
    ]);
    expect(first).toEqual([
      "G9001-2401",
      "Doris",
      "G9001",
      "Hona",
      "2024-05-01",
      "Högsta",
      "91",
      "10,3",
      "Enda kaninen i beräkningen med gener från founderdjuret G9001-1101",
    ]);
    expect(second.slice(0, 6)).toEqual([
      "G9002-2402",
      "",
      "G9001",
      "Okänt",
      "2024-05-01",
      "Övriga",
    ]);
    expect(rest).toEqual([]);
  });

  it("neutralises a name that starts like a formula and doubles quotes", () => {
    const csv = prioritiesCsv([
      row("G9001-2401", "critical", { name: '=HYPERLINK("x")' }),
    ]);
    expect(csv).toContain('" =HYPERLINK(""x"")"');
  });

  it("exports only the rows it is given, so a filtered list stays filtered", () => {
    const rows = [row("G9001-2401", "critical"), row("G9001-2402", "normal")];
    const csv = prioritiesCsv(rows.filter((r) => r.priority === "critical"));
    expect(parse(csv)).toHaveLength(2);
    expect(csv).not.toContain("G9001-2402");
  });
});

describe("byHerd", () => {
  it("keeps the levels in order and groups each level's rows per besättning", () => {
    const sorted = byHerd([
      row("G9002-1", "critical", { herd: "G9002" }),
      row("G9001-1", "important", { herd: "G9001" }),
      row("G9001-2", "critical", { herd: "G9001" }),
      row("G9002-2", "critical", { herd: "G9002" }),
    ]);
    expect(sorted.map((r) => r.individual_id)).toEqual([
      "G9001-2",
      "G9002-1",
      "G9002-2",
      "G9001-1",
    ]);
  });
});
