import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

const saleProposals = vi.fn();
const approveSale = vi.fn();
const rejectSale = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/arsrapport/actions", () => ({
  saleProposals: (...a: unknown[]) => saleProposals(...a),
  approveSale: (...a: unknown[]) => approveSale(...a),
  rejectSale: (...a: unknown[]) => rejectSale(...a),
}));

import { SalesDialog } from "@/app/(app)/stamboken/(dashboard)/arsrapport/status/[year]/SalesDialog";
import type { SaleProposalRow } from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(() => {
  cleanup();
  for (const f of [saleProposals, approveSale, rejectSale]) f.mockReset();
});

const inGenebank: SaleProposalRow = {
  id: 7,
  individual_id: 70,
  number: "G9001-2401",
  name: "Blomma",
  to_herd: "G9002",
  buyer: null,
  sale_date: "2025-10-03",
  buyer_notified_at: null,
  kopanmalan: null,
};
const outside: SaleProposalRow = {
  ...inGenebank,
  id: 8,
  individual_id: 80,
  number: "G9001-2402",
  name: null,
  to_herd: null,
  buyer: { name: "Zelda Uniquebuyer", town: "Visby" },
  sale_date: "2025-11-20",
  buyer_notified_at: "2026-01-11T10:00:00+00:00",
};

function open(onDecided = vi.fn()) {
  saleProposals.mockResolvedValue({
    ok: true,
    data: { forslag: [inGenebank, outside] },
  });
  render(
    <SalesDialog
      herd="G9001"
      year={2025}
      env="demo"
      onDecided={onDecided}
      onClose={vi.fn()}
    />,
  );
  return onDecided;
}

describe("SalesDialog", () => {
  it("lists each pending sale: the rabbit, the buyer and the date", async () => {
    open();
    const first = await screen.findByRole("region", { name: "G9001-2401" });
    expect(first.textContent).toContain("G9001-2401 Blomma");
    expect(first.textContent).toContain("till G9002");
    expect(first.textContent).toContain("3 oktober 2025");
    const second = screen.getByRole("region", { name: "G9001-2402" });
    expect(second.textContent).toContain(
      "utanför genbanken, Zelda Uniquebuyer, Visby",
    );
    expect(within(second).getByText("Köparen har anmält köpet")).toBeTruthy();
    expect(within(first).queryByText("Köparen har anmält köpet")).toBeNull();
  });

  it("shows the buyer's purchase notice beside the sale (fråga 19)", async () => {
    saleProposals.mockResolvedValue({
      ok: true,
      data: {
        forslag: [
          {
            ...inGenebank,
            kopanmalan: {
              id: 31,
              number: "G9001-2401",
              from_herd: "G9001",
              date: "2025-10-05",
              state: "ny",
            },
          },
        ],
      },
    });
    render(
      <SalesDialog
        herd="G9001"
        year={2025}
        env="demo"
        onDecided={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    const first = await screen.findByRole("region", { name: "G9001-2401" });
    expect(first.textContent).toContain(
      "Köparen har anmält köpet, 5 oktober 2025 · Visa anmälan",
    );
    expect(
      within(first)
        .getByRole("link", { name: "Visa anmälan" })
        .getAttribute("href"),
    ).toBe("/stamboken/inkorg/31");
  });

  it("approves a sale and reloads the list", async () => {
    approveSale.mockResolvedValue({
      ok: true,
      data: { id: 7, state: "godkand" },
    });
    const onDecided = open();
    const first = await screen.findByRole("region", { name: "G9001-2401" });
    fireEvent.click(within(first).getByText("Godkänn"));
    await waitFor(() => expect(onDecided).toHaveBeenCalled());
    expect(approveSale).toHaveBeenCalledWith(7, "demo");
    expect(saleProposals).toHaveBeenCalledTimes(2);
  });

  it("requires a reason and a choice before Avvisa", async () => {
    rejectSale.mockResolvedValue({
      ok: true,
      data: { id: 8, state: "avvisad" },
    });
    open();
    const second = await screen.findByRole("region", { name: "G9001-2402" });
    fireEvent.click(within(second).getByText("Avvisa …"));
    const avvisa = within(second).getByRole("button", {
      name: "Avvisa",
    }) as HTMLButtonElement;
    expect(avvisa.disabled).toBe(true);
    fireEvent.click(within(second).getByLabelText("Låt medlemmen välja igen"));
    expect(avvisa.disabled).toBe(true); // a choice without a reason
    fireEvent.change(within(second).getByLabelText(/Orsak/), {
      target: { value: "   " },
    });
    expect(avvisa.disabled).toBe(true); // blanks are no reason
    fireEvent.change(within(second).getByLabelText(/Orsak/), {
      target: { value: "Fel datum" },
    });
    expect(avvisa.disabled).toBe(false);
    fireEvent.click(avvisa);
    await waitFor(() =>
      expect(rejectSale).toHaveBeenCalledWith(
        8,
        "Fel datum",
        "valj_igen",
        "demo",
      ),
    );
  });

  it("shows the server's refusal and keeps the reason", async () => {
    rejectSale.mockResolvedValue({
      ok: false,
      problem: {
        status: 400,
        title: "Ogiltig begäran",
        detail: "Skriv orsaken utan köparens namn.",
      },
    });
    open();
    const second = await screen.findByRole("region", { name: "G9001-2402" });
    fireEvent.click(within(second).getByText("Avvisa …"));
    fireEvent.click(within(second).getByLabelText("Finns kvar 31 december"));
    fireEvent.change(within(second).getByLabelText(/Orsak/), {
      target: { value: "Zelda ångrade sig" },
    });
    fireEvent.click(within(second).getByRole("button", { name: "Avvisa" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Skriv orsaken utan köparens namn.",
    );
    expect(
      (within(second).getByLabelText(/Orsak/) as HTMLTextAreaElement).value,
    ).toBe("Zelda ångrade sig");
  });
});
