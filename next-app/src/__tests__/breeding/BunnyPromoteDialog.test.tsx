import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import "@/i18n";
import { BunnyPromoteDialog } from "@/components/herd/BunnyPromoteDialog";

const {
  promoteBunny,
  updateBreeding,
  checkIndividualNumber,
  checkLitterOrder,
  renumberLitters,
} = vi.hoisted(() => ({
  promoteBunny: vi.fn(),
  updateBreeding: vi.fn(),
  checkIndividualNumber: vi.fn(),
  checkLitterOrder: vi.fn(),
  renumberLitters: vi.fn(),
}));

vi.mock("@/app/(app)/stamboken/(dashboard)/min-besattning/actions", () => ({
  promoteBunny,
  updateBreeding,
  checkIndividualNumber,
  checkLitterOrder,
  renumberLitters,
  getColors: vi.fn().mockResolvedValue(null),
}));
vi.mock("@/lib/mode-context", () => ({ useMode: () => "prod" }));

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("BunnyPromoteDialog without alive at 6 weeks", () => {
  it("asks for it before a certificate and sends it with the registration", async () => {
    promoteBunny.mockResolvedValue({
      success: false,
      error:
        "Kullen har 3 levande i rostern men 2 levande vid 6 veckor. Markera 1 kaniner som döda innan intyg kan utfärdas.",
      errorTitle: "roster_alive_exceeds_6w",
    });
    render(
      <BunnyPromoteDialog
        open
        onClose={() => {}}
        onPromoted={() => {}}
        bunny={{
          id: 9,
          breeding_id: 4,
          slot_order: 1,
          observed_sex: "female",
          observed_color: "Viltgrå",
          label: null,
          notes: null,
          fate: "undecided",
          provisional_number: "G1-2511",
          individual: null,
        }}
        breeding={{ id: 4, litter_size: 4, litter_size6w: null }}
        herdId="G1"
      />,
    );
    const field = () =>
      screen.queryByLabelText(/Levande i kullen efter 6 veckor/);
    // A certificate is always issued (digital by default): the field shows at once
    expect(screen.getByText("Digitalt")).toBeTruthy(); // the certificate select
    const save = screen.getByRole("button", { name: "Registrera" });
    expect(field()).not.toBeNull();
    expect((save as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(field()!, { target: { value: "2" } });
    fireEvent.click(save);

    await screen.findByText(/Markera 1 kaniner som döda/);
    // Saved by the promote's own transaction: a refused registration leaves the litter as it was
    expect(promoteBunny).toHaveBeenCalledWith(
      9,
      expect.objectContaining({
        certificate_type: "digital",
        litter_size6w: 2,
      }),
    );
    await waitFor(() => expect(promoteBunny).toHaveBeenCalledTimes(1));
    // Refused for the roster: kept on the litter so the roster offers the kits to mark dead
    await waitFor(() =>
      expect(updateBreeding).toHaveBeenCalledWith(4, { litter_size6w: 2 }),
    );
  }, 20000); // the full MUI dialog renders slowly under the parallel suite

  it("leaves it unset when the paper's number conflicts", async () => {
    const check = {
      stamboken_number: "G1-2522",
      paper_number: "G1-2512",
      status: "conflict",
      conflicts: [],
      choices: ["use_stamboken_number", "paper_is_right"],
      actions: [],
    };
    checkIndividualNumber.mockResolvedValue({ success: true, data: check });
    promoteBunny.mockResolvedValue({
      success: false,
      error: "Individnumret på pappersintyget stämmer inte med Stambokens.",
      errorTitle: "number_conflict",
      numberCheck: check,
    });
    render(
      <BunnyPromoteDialog
        open
        onClose={() => {}}
        onPromoted={() => {}}
        bunny={{
          id: 9,
          breeding_id: 4,
          slot_order: 1,
          observed_sex: "female",
          observed_color: "Viltgrå",
          label: null,
          notes: null,
          fate: "undecided",
          provisional_number: "G1-2521",
          individual: null,
        }}
        breeding={{ id: 4, litter_size: 4, litter_size6w: null }}
        herdId="G1"
      />,
    );
    fireEvent.mouseDown(screen.getByText("Digitalt"));
    fireEvent.click(screen.getByRole("option", { name: /Papper/ }));
    fireEvent.change(screen.getByLabelText(/^Intygsnummer/), {
      target: { value: "P-77" },
    });
    fireEvent.change(screen.getByLabelText(/^Individnummer på pappret/), {
      target: { value: "G1-2512" },
    });
    fireEvent.change(screen.getByLabelText(/Levande i kullen efter 6 veckor/), {
      target: { value: "2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Registrera" }));

    await screen.findByRole("dialog", {
      name: "Individnumret på pappret stämmer inte med Stamboken",
    });
    expect(promoteBunny).toHaveBeenCalledWith(
      9,
      expect.objectContaining({ paper_number: "G1-2512", litter_size6w: 2 }),
    );
    expect(updateBreeding).not.toHaveBeenCalled();
  }, 20000); // the full MUI dialog renders slowly under the parallel suite
});

describe("BunnyPromoteDialog litter renumbering", () => {
  it("returns to the conflict dialog with an error when the renumber call rejects", async () => {
    promoteBunny.mockResolvedValue({
      success: false,
      error: "x",
      errorTitle: "litter_order_conflict",
    });
    checkLitterOrder.mockResolvedValue({
      success: true,
      data: {
        consistent: false,
        conflicts: [
          {
            breeding_id: 4,
            current_litter_number: 3,
            suggested_litter_number: 2,
            birth_date: "2025-05-01",
          },
        ],
      },
    });
    renumberLitters.mockRejectedValue(new Error("network down"));
    render(
      <BunnyPromoteDialog
        open
        onClose={() => {}}
        onPromoted={() => {}}
        bunny={{
          id: 9,
          breeding_id: 4,
          slot_order: 1,
          observed_sex: "female",
          observed_color: "Viltgrå",
          label: null,
          notes: null,
          fate: "undecided",
          provisional_number: "G1-2511",
          individual: null,
        }}
        breeding={{
          id: 4,
          litter_size: 4,
          litter_size6w: 2,
          birth_date: "2025-05-01",
        }}
        herdId="G1"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Registrera" }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Numrera om kullar automatiskt",
      }),
    );

    await screen.findByText("Kunde inte numrera om kullarna");
    // Not stuck: both buttons are usable again and the dialog can be dismissed.
    expect(
      (
        screen.getByRole("button", {
          name: "Numrera om kullar automatiskt",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
    expect(
      (screen.getByRole("button", { name: "Avbryt" }) as HTMLButtonElement)
        .disabled,
    ).toBe(false);
  }, 20000);
});
