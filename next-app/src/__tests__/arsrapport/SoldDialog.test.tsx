import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import "@/i18n"; // BuyerFields' labels
import {
  HerdPicker,
  SoldDialog,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/SoldDialog";
import type {
  BodyEntry,
  SaldState,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(cleanup);

const KEPT_TEXT =
  "Köparen finns sparad. Lämna fälten tomma om köparen är rätt, eller skriv en ny köpare.";
const ON_SEND_TEXT =
  "Köparens uppgifter sparas när du skickar rapporten, inte innan.";

function dialog(
  existing: SaldState | null,
  onSave = vi.fn(),
  canSell = true,
  submitted: BodyEntry["sald"] | null = null,
) {
  render(
    <SoldDialog
      open
      number="M9007-2412"
      year={2025}
      genebankId={2}
      ownHerd="M9007"
      loadHerds={() => new Promise(() => {})} // never answers
      existing={existing}
      submitted={submitted}
      canSell={canSell}
      addressRequired
      onSave={onSave}
      onClose={vi.fn()}
    />,
  );
  return onSave;
}

const save = () =>
  fireEvent.click(screen.getByRole("button", { name: "Spara försäljningen" }));

// The name and the town each say what is missing, at the field.
function expectBuyerAsked() {
  const name = screen.getByLabelText(/Köparens namn/);
  const town = screen.getByLabelText(/^Ort/);
  for (const [field, text] of [
    [name, "Skriv köparens namn."],
    [town, "Skriv köparens ort."],
    [screen.getByLabelText(/^Postadress/), "Skriv köparens postadress."],
  ] as const) {
    expect(field.getAttribute("aria-invalid")).toBe("true");
    const described = field.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(described)?.textContent).toBe(text);
  }
  expect(document.activeElement).toBe(name);
}

describe("SoldDialog", () => {
  it("gives the herd picker the member look, and leaves other pickers as they are", () => {
    dialog(null);
    expect(screen.getByTestId("herd-picker").className).toContain(
      "memberFields",
    );
    cleanup();
    render(
      <HerdPicker
        genebankId={2}
        ownHerd="M9007"
        loadHerds={async () => ({ success: true as const, herds: [] })}
        label="Säljarens besättning"
        value=""
        onChange={() => {}}
      />,
    );
    expect(screen.getByTestId("herd-picker").className).not.toContain(
      "memberFields",
    );
  });

  it("shows every refusal at its field at once, and focuses the first", () => {
    const onSave = dialog(null);
    const month = screen.getByLabelText("Månad");
    expect(month.getAttribute("aria-invalid")).toBe("false"); // nothing before Spara
    save();
    expect(onSave).not.toHaveBeenCalled();
    const herd = screen.getByLabelText("Köparens besättning");
    expect(herd.getAttribute("aria-invalid")).toBe("true");
    expect(
      document.getElementById(herd.getAttribute("aria-describedby") ?? "")
        ?.textContent,
    ).toBe("Välj en besättning i genbanken, eller Utanför genbanken.");
    expect(month.getAttribute("aria-invalid")).toBe("true");
    expect(
      document.getElementById(month.getAttribute("aria-describedby") ?? "")
        ?.textContent,
    ).toBe("Välj månad.");
    expect(document.activeElement).toBe(herd);
    fireEvent.change(month, { target: { value: "6" } });
    expect(screen.queryByText("Välj månad.")).toBeNull(); // gone once chosen
    expect(month.getAttribute("aria-invalid")).toBe("false");
  });

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
    expect(screen.getByTestId("sell-buyer").className).toContain(
      "memberFields",
    ); // the member's larger fields
    expect(screen.getByText(ON_SEND_TEXT)).toBeTruthy();
    expect(screen.queryByLabelText(/E-post/)).toBeNull(); // only with a yes
    fireEvent.change(screen.getByLabelText(/Köparens namn/), {
      target: { value: "Ola Köpare" },
    });
    fireEvent.change(screen.getByLabelText(/^Ort/), {
      target: { value: "Visby" },
    });
    fireEvent.change(screen.getByLabelText(/^Postadress/), {
      target: { value: "Testgatan 1" },
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
        postal_address: "Testgatan 1",
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
    expect(screen.queryByText(ON_SEND_TEXT)).toBeNull(); // not beside "finns sparad"
    save();
    expect(onSave).toHaveBeenCalledWith({ ...kept });
  });

  it("asks a role whose sale is a proposal to type the buyer, as a kept one is not theirs", () => {
    const kept: SaldState = {
      till: "utanfor",
      ar: 2025,
      manad: 10,
      dag: 10,
      kopare: null,
      kopare_id: 7,
    };
    const onSave = dialog(kept, vi.fn(), false);
    expect(screen.queryByText(KEPT_TEXT)).toBeNull();
    expect(screen.queryByText(/Lämna fälten tomma/)).toBeNull();
    expect(screen.getByText(ON_SEND_TEXT)).toBeTruthy();
    save();
    expect(onSave).not.toHaveBeenCalled();
    expectBuyerAsked();
    fireEvent.change(screen.getByLabelText(/Köparens namn/), {
      target: { value: "Ola Köpare" },
    });
    fireEvent.change(screen.getByLabelText(/^Ort/), {
      target: { value: "Visby" },
    });
    fireEvent.change(screen.getByLabelText(/^Postadress/), {
      target: { value: "Testgatan 1" },
    });
    save();
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        kopare: expect.objectContaining({ name: "Ola Köpare", town: "Visby" }),
      }),
    );
  });

  it("lets the fields stay empty only for the sale the report holds unchanged", () => {
    const sale = { till: "utanfor", ar: 2025, manad: 10, dag: 10 };
    const onSave = dialog({ ...sale, kopare: null }, vi.fn(), true, sale);
    expect(
      screen.getByText(/Lämna fälten tomma om köparen är rätt/),
    ).toBeTruthy();
    save();
    expect(onSave).toHaveBeenCalledWith({ ...sale, kopare: null });
    onSave.mockClear();
    fireEvent.change(screen.getByLabelText("Månad"), {
      target: { value: "11" },
    });
    expect(screen.queryByText(/Lämna fälten tomma/)).toBeNull(); // a changed sale is a new one
    save();
    expect(onSave).not.toHaveBeenCalled();
    expectBuyerAsked();
  });

  it("asks for the buyer again for a sale only in the draft, after a reload (Codex P2)", () => {
    // The draft keeps the sale but never its buyer, and Skicka needs one (kopare_saknas).
    const onSave = dialog({
      till: "utanfor",
      ar: 2025,
      manad: 10,
      dag: 10,
      kopare: null,
    });
    expect(screen.queryByText(/Lämna fälten tomma/)).toBeNull();
    expect(screen.getByText(ON_SEND_TEXT)).toBeTruthy();
    save();
    expect(onSave).not.toHaveBeenCalled();
    expectBuyerAsked();
  });
});
