import { describe, it, expect } from "vitest";
import { generateTempPassword } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/password";

describe("generateTempPassword", () => {
  it("is 22 chars of base64url (16 random bytes, no padding)", () => {
    const pw = generateTempPassword();
    expect(pw).toMatch(/^[A-Za-z0-9_-]{22}$/);
  });

  it("produces distinct values (cryptographic RNG, not a constant)", () => {
    const seen = new Set(Array.from({ length: 20 }, generateTempPassword));
    expect(seen.size).toBe(20);
  });
});
