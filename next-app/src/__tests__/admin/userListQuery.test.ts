import { describe, expect, test } from "vitest";
import { userListQuery } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/userListQuery";

describe("userListQuery (#249)", () => {
  test("keeps the list's own keys in a fixed order and drops the rest", () => {
    expect(
      userListQuery({
        active: "false",
        search: "a b&c",
        returnTo: "https://example.org",
        page: "2",
        role: "",
      }),
    ).toBe("search=a+b%26c&active=false&page=2");
  });

  test("is empty for an unfiltered list", () => {
    expect(userListQuery({})).toBe("");
  });
});
