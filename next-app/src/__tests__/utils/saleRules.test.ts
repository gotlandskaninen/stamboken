import { describe, it, expect, afterEach, vi } from "vitest";
import {
  isOutsideGenebankHerd,
  minSaleDate,
  stockholmToday,
  toIsoDate,
  validateSaleDate,
} from "@/utils/saleRules";

describe("minSaleDate", () => {
  it("is birth + 43 days when the latest tracking row is the birth row", () => {
    const min = minSaleDate("2021-02-01", [{ date: "2021-02-01" }]);
    expect(toIsoDate(min!)).toBe("2021-03-16");
  });

  it("is birth + 43 days when there is no tracking at all", () => {
    expect(toIsoDate(minSaleDate("2021-02-01", [])!)).toBe("2021-03-16");
    expect(toIsoDate(minSaleDate("2021-02-01", null)!)).toBe("2021-03-16");
  });

  it("is the day after the latest tracking date otherwise (order-independent)", () => {
    const min = minSaleDate("2021-02-01", [
      { date: "2021-02-01" },
      { date: "2021-06-10" },
      { date: "2021-04-01" },
    ]);
    expect(toIsoDate(min!)).toBe("2021-06-11");
  });

  it("returns null without any dates", () => {
    expect(minSaleDate(null, [])).toBeNull();
  });
});

describe("validateSaleDate", () => {
  const today = new Date(2026, 9, 1);
  const min = new Date(2026, 8, 1);

  it("accepts today and the minimum date", () => {
    expect(
      validateSaleDate(new Date(2026, 9, 1, 23, 59), min, today),
    ).toBeNull();
    expect(validateSaleDate(new Date(2026, 8, 1), min, today)).toBeNull();
  });

  it("rejects future, too early and missing/invalid dates", () => {
    expect(validateSaleDate(new Date(2026, 9, 2), min, today)).toBe("future");
    expect(validateSaleDate(new Date(2026, 7, 31), min, today)).toBe(
      "tooEarly",
    );
    expect(validateSaleDate(null, min, today)).toBe("invalid");
    expect(validateSaleDate(new Date("nope"), min, today)).toBe("invalid");
  });
});

describe("stockholmToday", () => {
  afterEach(() => vi.useRealTimers());

  it("uses the Stockholm date, not the browser's: already tomorrow there, still today in New York", () => {
    // 22:30 UTC = 00:30 CEST in Stockholm (Oct 2) but 18:30 EDT in New York (Oct 1).
    const instant = new Date("2026-10-01T22:30:00Z");
    expect(toIsoDate(stockholmToday(instant))).toBe("2026-10-02");
  });

  it("handles winter time (CET, UTC+1)", () => {
    expect(toIsoDate(stockholmToday(new Date("2026-01-15T23:30:00Z")))).toBe(
      "2026-01-16",
    );
    expect(toIsoDate(stockholmToday(new Date("2026-01-15T22:30:00Z")))).toBe(
      "2026-01-15",
    );
  });

  it("is what validateSaleDate checks against by default", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-01T22:30:00Z"));
    expect(validateSaleDate(new Date(2026, 9, 2), null)).toBeNull();
    expect(validateSaleDate(new Date(2026, 9, 3), null)).toBe("future");
  });
});

describe("isOutsideGenebankHerd", () => {
  it("recognises GX1 and MX1 only", () => {
    expect(isOutsideGenebankHerd("GX1")).toBe(true);
    expect(isOutsideGenebankHerd("MX1")).toBe(true);
    expect(isOutsideGenebankHerd("G1274")).toBe(false);
  });
});
