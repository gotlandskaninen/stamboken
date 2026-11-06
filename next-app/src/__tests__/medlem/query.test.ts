import { describe, expect, it } from "vitest";
import { positiveInt } from "@/app/(app)/medlem/matrikel/query";

describe("positiveInt", () => {
  it("accepts positive integers only", () => {
    expect(positiveInt("7")).toBe(7);
    expect(positiveInt(["3", "4"])).toBe(3);
  });
  it("rejects fractions, zero, negatives, garbage and absence", () => {
    for (const bad of ["1.5", "0", "-2", "abc", "", undefined])
      expect(positiveInt(bad)).toBeNull();
  });
  it("rejects values past the safe-integer range", () => {
    // page.tsx forwards the value to the API before its clamp redirect, so a
    // value Number() cannot represent exactly must fall back to the default
    // rather than reach Flask's int().
    expect(positiveInt("9007199254740991")).toBe(9007199254740991);
    expect(positiveInt("9007199254740992")).toBeNull();
    expect(positiveInt("9".repeat(400))).toBeNull(); // Number(...) === Infinity
  });
  it("rejects Number()-coercible forms that are not decimal digits", () => {
    // Number("1e3") === 1000 and Number("1.0") === 1 are integers, so the
    // digits-only guard is what keeps them out; "01" is a leading zero, not
    // how a positive integer is written in a URL.
    for (const bad of ["1e3", "1.0", "01", " 7 ", "0x10", "+5", "Infinity"])
      expect(positiveInt(bad)).toBeNull();
  });
});
