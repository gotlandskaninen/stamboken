import { describe, it, expect } from "vitest";
import {
  rabbitStatus,
  mbAge,
  mbGestation,
} from "@/app/(app)/stamboken/(dashboard)/min-besattning/min-besattning-ui";

const base = {
  death_date: null,
  alive: true,
  is_active: true,
} as any;

describe("rabbitStatus", () => {
  it("maps living reported rabbits to Aktiv", () => {
    expect(rabbitStatus(base)).toBe("Aktiv");
  });
  it("death_date or alive=false wins over everything", () => {
    expect(rabbitStatus({ ...base, death_date: "2025-11-02" })).toBe("Död");
    expect(rabbitStatus({ ...base, alive: false })).toBe("Död");
  });
  it("not yearly-reported maps to Inaktiv", () => {
    expect(rabbitStatus({ ...base, is_active: false })).toBe("Inaktiv");
  });
});

describe("mbAge", () => {
  it("handles missing birth date", () => {
    expect(mbAge(null)).toBe("—");
    expect(mbAge(undefined)).toBe("—");
  });
  it("renders years for old rabbits", () => {
    expect(mbAge("2019-01-01")).toMatch(/år/);
  });
});

describe("mbGestation", () => {
  it("clamps pct at 100 and computes due = mating + 31 days", () => {
    const g = mbGestation("2020-01-01");
    expect(g.pct).toBe(100);
    expect(g.due).toBe("2020-02-01");
  });
});
