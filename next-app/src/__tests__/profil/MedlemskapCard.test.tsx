import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { MedlemskapCard } from "@/app/(app)/stamboken/(dashboard)/profil/MedlemskapCard";
import type { MembershipStatus } from "@/lib/membershipStatus";
import type { Me } from "@/app/(app)/stamboken/(dashboard)/profil/types";

const me = (
  status: Me["membership"]["membership_status"],
  role: Me["role"] = "familjemedlem",
): Me => ({
  id: 2,
  first_name: "Erik",
  last_name: "Lindqvist",
  email: null,
  phone: null,
  role,
  membership: {
    id: 1,
    member_number: 1274,
    membership_status: status,
    address: null,
    postal_code: null,
    city: null,
    postal_address: null,
    joined_date: "2019-03-01",
  },
  publication_consent: {
    name: false,
    phone: false,
    email: false,
    address: false,
  },
  consent_answered: false,
  main_member_name: "Anna Lindqvist",
});
afterEach(cleanup);

describe("MedlemskapCard", () => {
  it.each<[MembershipStatus, string]>([
    ["active", "Aktiv"],
    ["inactive", "Inaktiv"],
    ["pending", "Väntar"],
    ["friexemplar", "Friexemplar"],
  ])("maps status %s to badge %s", (status, label) => {
    render(<MedlemskapCard me={me(status)} herds={[]} />);
    expect(screen.getByText(label)).toBeDefined();
  });
  it("shows number, joined date, huvudmedlem and own role", () => {
    render(
      <MedlemskapCard
        me={me("active")}
        herds={[{ id: 3, herd: "G1274", herd_name: "Solhaga" }]}
      />,
    );
    expect(screen.getByText("1274")).toBeDefined();
    expect(screen.getByText("2019-03-01")).toBeDefined();
    expect(screen.getByText("Anna Lindqvist")).toBeDefined();
    expect(screen.getByText("Familjemedlem")).toBeDefined();
    expect(
      screen
        .getByRole("link", { name: "G1274 — Solhaga" })
        .getAttribute("href"),
    ).toBe("/stamboken/min-besattning?herd=G1274");
  });
  it("falls back to a dash without an active huvudmedlem", () => {
    render(
      <MedlemskapCard
        me={{ ...me("active"), main_member_name: null }}
        herds={[]}
      />,
    );
    expect(screen.getByText("–")).toBeDefined();
  });
});
