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
  RabbitView,
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
  rabbit?: Partial<RabbitView>,
  year = 2025,
) {
  render(
    <SoldDialog
      open
      number="M9007-2412"
      year={year}
      genebankId={2}
      ownHerd="M9007"
      loadHerds={() => new Promise(() => {})} // never answers
      existing={existing}
      submitted={submitted}
      rabbit={rabbit}
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

// The buyer is asked first how they are recorded (#273: "Har köparen e-post?" before 2027), then
// the name, town, address and e-mail each say what is missing, at the field.
function expectBuyerAsked() {
  expect(screen.getByText("Välj om köparen har e-post.")).toBeTruthy();
  expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
  expect(document.activeElement).toBe(
    screen.getByRole("radio", { name: "Ja" }),
  ); // the refused choice takes the focus
  fireEvent.click(screen.getByRole("radio", { name: "Ja" }));
  for (const [field, text] of [
    [screen.getByLabelText(/Köparens namn/), "Skriv köparens namn."],
    [screen.getByLabelText(/^Ort/), "Skriv köparens ort."],
    [screen.getByLabelText(/^Postadress/), "Skriv köparens postadress."],
    [screen.getByLabelText(/^E-post/), "Skriv köparens e-post."],
  ] as const) {
    expect(field.getAttribute("aria-invalid")).toBe("true");
    const described = field.getAttribute("aria-describedby") ?? "";
    expect(document.getElementById(described)?.textContent).toBe(text);
  }
}

const typeEpostBuyer = () => {
  for (const [label, value] of [
    [/Köparens namn/, "Ola Köpare"],
    [/^Ort/, "Visby"],
    [/^Postadress/, "Testgatan 1"],
    [/^E-post/, "ola@example.invalid"],
  ] as const)
    fireEvent.change(screen.getByLabelText(label), { target: { value } });
};

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

  it("takes the buyer outside the genebank in BuyerFields, with the buyer's yes (a bevis, from 2028)", () => {
    const onSave = dialog(null, vi.fn(), true, null, undefined, 2028);
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    expect(screen.getByTestId("sell-buyer").className).toContain(
      "memberFields",
    ); // the member's larger fields
    expect(screen.queryByRole("radio", { name: "Ja" })).toBeNull(); // no choice from 2028
    expect(screen.getByText(ON_SEND_TEXT)).toBeTruthy();
    expect(screen.queryByText(/Ge köparen försäljningsbeviset/)).toBeNull(); // the sale has happened
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
      ar: 2028,
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

  it("takes the e-mail buyer for the association's notice before 2027", () => {
    const onSave = dialog(null);
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    expect(screen.getByText("Har köparen e-post?")).toBeTruthy();
    expect(screen.queryByLabelText(/Köparens namn/)).toBeNull(); // not before the choice
    fireEvent.click(screen.getByRole("radio", { name: "Ja" }));
    expect(screen.queryByRole("checkbox")).toBeNull(); // no consent boxes
    typeEpostBuyer();
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
        email: "ola@example.invalid",
        notice_only: true,
      },
    });
  });

  it("saves a sale outside the genebank with no buyer kept when the buyer has no e-mail", () => {
    const onSave = dialog(null);
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    fireEvent.click(
      screen.getByRole("radio", { name: "Nej, såld utanför genbanken" }),
    );
    expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Månad"), {
      target: { value: "6" },
    });
    save();
    expect(onSave).toHaveBeenCalledWith({
      till: "utanfor",
      ar: 2025,
      manad: 6,
      dag: null,
      kopare: { not_recorded: true },
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
    const onSave = dialog(kept, vi.fn(), true, null, {
      kept_buyer_date: "2025-10-10",
    });
    expect(screen.getByText(KEPT_TEXT)).toBeTruthy();
    expect(screen.queryByText(/sparas inte i rapporten/)).toBeNull();
    expect(screen.queryByText(ON_SEND_TEXT)).toBeNull(); // not beside "finns sparad"
    save();
    expect(onSave).toHaveBeenCalledWith({ ...kept });
    onSave.mockClear();
    fireEvent.change(screen.getByLabelText("Månad"), {
      target: { value: "11" },
    });
    save();
    expect(onSave).not.toHaveBeenCalled();
    expectBuyerAsked();
  });

  it("changes the date of a sale with an erased buyer without asking for their details", () => {
    const sale = {
      till: "utanfor",
      ar: 2025,
      manad: 10,
      dag: 10,
      kopare: null,
    };
    const onSave = dialog(sale, vi.fn(), true, null, { buyer_removed: true });
    fireEvent.change(screen.getByLabelText("Månad"), {
      target: { value: "11" },
    });
    expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
    save();
    expect(onSave).toHaveBeenCalledWith({ ...sale, manad: 11 });
  });

  it("asks for a new buyer when only an earlier sale's buyer was erased", () => {
    const sale = {
      till: "utanfor",
      ar: 2025,
      manad: 10,
      dag: 10,
      kopare: null,
    };
    const onSave = dialog(sale, vi.fn(), true, null, {
      removed_buyer_dates: ["2025-10-10"],
    });
    expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
    fireEvent.change(screen.getByLabelText("Månad"), {
      target: { value: "11" },
    });
    save();
    expect(onSave).not.toHaveBeenCalled();
    expectBuyerAsked();
  });

  it("requires a replacement buyer's address on a pending proposal", () => {
    const sale = { till: "utanfor", ar: 2025, manad: 10, dag: 10 };
    const onSave = dialog({ ...sale, kopare: null }, vi.fn(), true, sale);
    fireEvent.click(screen.getByRole("radio", { name: "Ja" }));
    fireEvent.change(screen.getByLabelText(/Köparens namn/), {
      target: { value: "Ola Köpare" },
    });
    fireEvent.change(screen.getByLabelText(/^Ort/), {
      target: { value: "Visby" },
    });
    save();
    expect(screen.getByText("Skriv köparens postadress.")).toBeTruthy();
    expect(screen.getByText("Skriv köparens e-post.")).toBeTruthy();
    expect(onSave).not.toHaveBeenCalled();
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
    typeEpostBuyer();
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
