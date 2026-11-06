import { describe, it, expect } from "vitest";
import { formatPostalCode, isValidPostalCode } from "@/lib/postal";

describe("formatPostalCode", () => {
  it("inserts the space after the third digit", () => {
    expect(formatPostalCode("62355")).toBe("623 55");
    expect(formatPostalCode(" 62355 ")).toBe("623 55");
  });
  it("leaves spaced and non-matching input alone (server validates)", () => {
    expect(formatPostalCode("623 55")).toBe("623 55");
    expect(formatPostalCode("6235")).toBe("6235");
    expect(formatPostalCode("")).toBe("");
  });
});

describe("isValidPostalCode", () => {
  it("accepts blank, compact and spaced five-digit codes", () => {
    for (const ok of ["", "62355", "623 55", " 623 55 "])
      expect(isValidPostalCode(ok)).toBe(true);
  });
  it("rejects everything else", () => {
    for (const bad of ["6235", "623555", "S-623 55", "abcde"])
      expect(isValidPostalCode(bad)).toBe(false);
  });
});
