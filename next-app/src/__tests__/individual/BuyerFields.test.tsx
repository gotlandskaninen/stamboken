import React from "react";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  BuyerFields,
  EMPTY_BUYER,
  buyerComplete,
  buyerModes,
  buyerPayload,
  type BuyerDraft,
} from "@/components/individual/BuyerFields";

beforeAll(async () => {
  await import("@/i18n");
});
afterEach(cleanup);

const filled = (changes: Partial<BuyerDraft>): BuyerDraft => ({
  ...EMPTY_BUYER,
  name: " Anna Köpare ",
  town: "Visby",
  postal_address: "Väg 1",
  email: "anna@example.org",
  ...changes,
});

describe("buyerModes", () => {
  it("follows the sale's year (#273)", () => {
    expect(buyerModes(2025)).toEqual(["epost", "utan"]);
    expect(buyerModes(2026)).toEqual(["bevis", "epost", "utan"]);
    expect(buyerModes(2027)).toEqual(["bevis", "epost", "utan"]);
    expect(buyerModes(2028)).toEqual(["bevis"]);
  });

  it("starts the bevis a year later in the yearly report", () => {
    expect(buyerModes(2026, true)).toEqual(["epost", "utan"]);
    expect(buyerModes(2027, true)).toEqual(["bevis", "epost", "utan"]);
    expect(buyerModes(2028, true)).toEqual(["bevis"]);
  });
});

describe("buyerPayload", () => {
  it("sends nothing kept for utan", () => {
    expect(buyerPayload(filled({ mode: "utan" }), 2026)).toEqual({
      not_recorded: true,
    });
  });

  it("sends the e-mail for the notice only for epost", () => {
    expect(
      buyerPayload(filled({ mode: "epost", phone: "0700000000" }), 2026),
    ).toEqual({
      name: "Anna Köpare",
      town: "Visby",
      postal_address: "Väg 1",
      email: "anna@example.org",
      notice_only: true,
    });
  });

  it("keeps the old shape for bevis, with e-mail only after a yes", () => {
    const bevis = filled({ mode: "bevis", phone: "0700000000" });
    expect(buyerPayload(bevis, 2027)).toEqual({
      name: "Anna Köpare",
      town: "Visby",
      contact_consent: false,
      membership_optin: false,
      postal_address: "Väg 1",
    });
    expect(
      buyerPayload({ ...bevis, contact_consent: true }, 2027),
    ).toMatchObject({ email: "anna@example.org", phone: "0700000000" });
  });

  it("is bevis from 2028 without a chosen mode", () => {
    expect(buyerPayload(filled({}), 2028)).toHaveProperty("contact_consent");
  });
});

describe("buyerComplete", () => {
  it("needs address and e-mail for epost", () => {
    const epost = filled({ mode: "epost" });
    expect(buyerComplete(epost, false, 2026)).toBe(true);
    expect(buyerComplete({ ...epost, postal_address: " " }, false, 2026)).toBe(
      false,
    );
    expect(buyerComplete({ ...epost, email: "" }, false, 2026)).toBe(false);
  });

  it("is complete for utan, and incomplete before a choice in 2026", () => {
    expect(buyerComplete({ ...EMPTY_BUYER, mode: "utan" }, true, 2026)).toBe(
      true,
    );
    expect(buyerComplete(filled({}), false, 2026)).toBe(false);
  });

  it("asks for the address of a bevis only when required", () => {
    const bevis = filled({ mode: "bevis", postal_address: "" });
    expect(buyerComplete(bevis, false, 2027)).toBe(true);
    expect(buyerComplete(bevis, true, 2027)).toBe(false);
  });
});

describe("BuyerFields", () => {
  const show = (year: number, variant?: "member", inReport?: boolean) =>
    render(
      <BuyerFields
        value={{ ...EMPTY_BUYER, mode: "bevis" }}
        onChange={() => {}}
        year={year}
        variant={variant}
        inReport={inReport}
      />,
    );
  const CONSENT =
    "Köparen har kryssat ja: föreningen får spara e-post och telefon så länge köparen har kaninen";

  it("asks 'Fick köparen försäljningsbeviset?' in 2026 outside the report", () => {
    show(2026);
    expect(screen.getByText("Fick köparen försäljningsbeviset?")).toBeTruthy();
    expect(screen.getAllByRole("radio")).toHaveLength(3);
  });

  it("asks 'Har köparen e-post?' in 2026 in the report, with no consent boxes", () => {
    show(2026, undefined, true);
    expect(screen.getByText("Har köparen e-post?")).toBeTruthy();
    expect(screen.getAllByRole("radio")).toHaveLength(2);
    expect(screen.queryByRole("checkbox", { name: CONSENT })).toBeNull();
  });

  it("asks 'Fick köparen försäljningsbeviset?' in 2027, with the bevis fields after Ja", () => {
    show(2027);
    expect(screen.getByText("Fick köparen försäljningsbeviset?")).toBeTruthy();
    expect(
      screen.getAllByRole("radio").map((r) => r.closest("label")?.textContent),
    ).toEqual([
      "Ja",
      "Nej, men köparen har e-post",
      "Nej, och köparen har ingen e-post: såld utanför genbanken",
    ]);
    expect(screen.getByRole("checkbox", { name: CONSENT })).toBeTruthy();
  });

  it("shows no radio and the consent boxes in 2028", () => {
    show(2028);
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.getByRole("checkbox", { name: CONSENT })).toBeTruthy();
    expect(screen.getByText(/Ge köparen försäljningsbeviset/)).toBeTruthy();
  });

  it("never shows the proof note in the member variant", () => {
    show(2028, "member");
    expect(screen.getByRole("checkbox", { name: CONSENT })).toBeTruthy();
    expect(screen.queryByText(/Ge köparen försäljningsbeviset/)).toBeNull();
  });
});
