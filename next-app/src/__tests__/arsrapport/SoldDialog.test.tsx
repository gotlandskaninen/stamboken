import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@/i18n"; // BuyerFields' labels
import { SoldDialog } from "@/app/(app)/stamboken/(dashboard)/arsrapport/SoldDialog";
import type { SaldState } from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(cleanup);

const KEPT_TEXT =
  "Köparen finns sparad. Lämna fälten tomma om köparen är rätt, eller skriv en ny köpare.";
const ON_SEND_TEXT =
  "Köparens uppgifter sparas när du skickar rapporten, inte innan.";

function dialog(existing: SaldState | null, onSave = vi.fn(), canSell = true) {
  render(
    <SoldDialog
      open
      number="M9007-2412"
      year={2025}
      genebankId={2}
      ownHerd="M9007"
      loadHerds={() => new Promise(() => {})} // never answers
      existing={existing}
      canSell={canSell}
      onSave={onSave}
      onClose={vi.fn()}
    />,
  );
  return onSave;
}

const save = () =>
  fireEvent.click(screen.getByRole("button", { name: "Spara försäljningen" }));

describe("SoldDialog", () => {
  it("saves a changed sale to a herd at once, before the herd list has arrived", () => {
    const onSave = dialog({
      till: "M9001",
      ar: 2025,
      manad: 12,
      dag: 31,
      kopare: null,
    });
    save();
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ till: "M9001", ar: 2025, manad: 12, dag: 31 }),
    );
  });

  it("takes the buyer outside the genebank in BuyerFields, with the buyer's yes", () => {
    const onSave = dialog(null);
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    expect(screen.getByTestId("sell-buyer")).toBeTruthy();
    expect(screen.getByText(ON_SEND_TEXT)).toBeTruthy();
    expect(screen.queryByLabelText(/E-post/)).toBeNull(); // only with a yes
    fireEvent.change(screen.getByLabelText(/Köparens namn/), {
      target: { value: "Ola Köpare" },
    });
    fireEvent.change(screen.getByLabelText(/^Ort/), {
      target: { value: "Visby" },
    });
    fireEvent.click(
      screen.getByLabelText(
        "Köparen har kryssat ja: föreningen får kontakta köparen om medlemskap",
      ),
    );
    fireEvent.change(screen.getByLabelText(/E-post/), {
      target: { value: "ola@example.invalid" },
    });
    fireEvent.change(screen.getByLabelText("Månad"), {
      target: { value: "6" },
    });
    save();
    expect(onSave).toHaveBeenCalledWith({
      till: "utanfor",
      ar: 2025,
      manad: 6,
      dag: null,
      kopare: {
        name: "Ola Köpare",
        town: "Visby",
        contact_consent: false,
        membership_optin: true,
        email: "ola@example.invalid",
      },
    });
  });

  it("says a kept buyer is saved, and keeps its id when the fields stay empty", () => {
    const kept: SaldState = {
      till: "utanfor",
      ar: 2025,
      manad: 10,
      dag: 10,
      kopare: null,
      kopare_id: 7,
    };
    const onSave = dialog(kept);
    expect(screen.getByText(KEPT_TEXT)).toBeTruthy();
    expect(screen.queryByText(/sparas inte i rapporten/)).toBeNull();
    save();
    expect(onSave).toHaveBeenCalledWith({ ...kept });
  });

  it("shows no kept buyer to a role whose sale is a proposal", () => {
    dialog(
      {
        till: "utanfor",
        ar: 2025,
        manad: 10,
        dag: 10,
        kopare: null,
        kopare_id: 7,
      },
      vi.fn(),
      false,
    );
    expect(screen.queryByText(KEPT_TEXT)).toBeNull();
  });
});
