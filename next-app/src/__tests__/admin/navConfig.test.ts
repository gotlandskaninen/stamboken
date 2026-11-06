import { describe, it, expect } from "vitest";
import {
  NAV_CONFIG,
  adminRoleLine,
  hasAnyVisible,
  isMemberAdmin,
} from "@/app/(app)/stamboken/(dashboard)/admin/_components/navConfig";
import type { UserContext } from "@/lib/user-context";

function makeUser(overrides: Partial<UserContext>): UserContext {
  return {
    id: 1,
    email: "test@example.com",
    fullname: null,
    username: "testuser",
    validated: false,
    is_admin: false,
    is_manager: null,
    is_owner: null,
    is_matrikel_admin: false,
    profile_picture: null,
    google_picture: null,
    google_name: null,
    google_email: null,
    use_google_picture: false,
    v2_prod_access: false,
    ...overrides,
  };
}

const visibleHrefs = (user: UserContext) =>
  NAV_CONFIG.flatMap((g) => g.items)
    .filter((i) => i.show({ user }))
    .map((i) => i.href);

describe("NAV_CONFIG predicates", () => {
  it("admin sees every item, incl. all 4 SYSTEM items", () => {
    const admin = makeUser({ is_admin: true });
    expect(visibleHrefs(admin)).toEqual([
      "/stamboken/admin/anvandare",
      "/stamboken/admin/besattningar",
      "/stamboken/admin/genbanker",
      "/stamboken/admin/system/online",
      "/stamboken/admin/system/audit",
      "/stamboken/admin/system/synk",
      "/stamboken/admin/system/ratelimit",
    ]);
    expect(hasAnyVisible(admin)).toBe(true);
  });

  it("manager(gb) sees only besättningar + genbanker", () => {
    const manager = makeUser({ is_manager: [1] });
    expect(visibleHrefs(manager)).toEqual([
      "/stamboken/admin/besattningar",
      "/stamboken/admin/genbanker",
    ]);
    expect(hasAnyVisible(manager)).toBe(true);
  });

  it("owner-only user sees nothing → layout 404", () => {
    const owner = makeUser({ is_owner: ["G1"] });
    expect(visibleHrefs(owner)).toEqual([]);
    expect(hasAnyVisible(owner)).toBe(false);
    expect(isMemberAdmin(owner)).toBe(false);
  });

  it("matrikel admin has no nav items but passes the gate via isMemberAdmin", () => {
    const matrikel = makeUser({ is_matrikel_admin: true });
    expect(visibleHrefs(matrikel)).toEqual([]);
    expect(isMemberAdmin(matrikel)).toBe(true);
    expect(hasAnyVisible(matrikel)).toBe(true);
    // The same trio as the API's check_matrikel_access.
    expect(isMemberAdmin(makeUser({ is_manager: [1] }))).toBe(true);
    expect(isMemberAdmin(makeUser({ is_admin: true }))).toBe(true);
  });

  it("manager label variant interpolates genebank names", () => {
    const manager = makeUser({ is_manager: [1] });
    const item = NAV_CONFIG.find((g) => g.label === "BESÄTTNINGAR")!.items[0];
    expect(item.label({ user: manager, gbNames: ["Gotlandskaninen"] })).toBe(
      "Besättningar i Gotlandskaninen",
    );
    const admin = makeUser({ is_admin: true });
    expect(item.label({ user: admin })).toBe("Alla besättningar");
  });
});

describe("adminRoleLine (masthead)", () => {
  it("names each of the three roles the layout gate admits", () => {
    expect(adminRoleLine(makeUser({ is_admin: true }))).toBe(
      "Inloggad som administratör",
    );
    expect(
      adminRoleLine(makeUser({ is_manager: [1] }), ["Gotlandskanin"]),
    ).toBe("Inloggad som genbanksansvarig · Gotlandskanin");
    expect(adminRoleLine(makeUser({ is_manager: [1] }))).toBe(
      "Inloggad som genbanksansvarig",
    );
    // A matrikel-only admin is not a genbanksansvarig.
    expect(adminRoleLine(makeUser({ is_matrikel_admin: true }))).toBe(
      "Inloggad som matrikeladministratör",
    );
  });
});
