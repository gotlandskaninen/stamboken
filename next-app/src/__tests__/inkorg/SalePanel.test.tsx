import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const registerSale = vi.fn();
const rabbitSales = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/actions", () => ({
  registerSale: (...args: unknown[]) => registerSale(...args),
  rabbitSales: (...args: unknown[]) => rabbitSales(...args),
}));

import { SalePanel } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/SalePanel";
import type { InboxDocument } from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

beforeAll(async () => {
  await import("@/i18n");
});

afterEach(() => {
  cleanup();
  registerSale.mockReset();
  rabbitSales.mockReset();
});

const CONSENT =
  "Köparen har kryssat ja: föreningen får spara e-post och telefon så länge köparen har kaninen";
const OPTIN =
  "Köparen har kryssat ja: föreningen får kontakta köparen om medlemskap";

const doc = {
  id: 31,
  status: "ny",
  mime: "image/jpeg",
  warnings: [],
  duplicates: [],
  doc_type: "bevis",
  cert_format: null,
  rotation: 0,
  mask_rects: null,
  mask_suggestion: null,
  waiting_for: null,
  interpretation_status: "av",
  proposal: null,
  individual: "G9001-2511",
  has_copy: false,
} as unknown as InboxDocument;

// G9001-2511's sale to GX1 on 2026-10-03, registered anywhere (the sell dialog or the item).
const sale = {
  herd: "GX1",
  date: "2026-10-03",
  kind: "TRANSFER",
  buyer: "present",
};
const found = (...sales: object[]) => ({ ok: true, data: { sales } });
const registered = found(sale);

function panel(answer: object = found(), addressRequired = false) {
  rabbitSales.mockResolvedValue(answer);
  render(
    <SalePanel
      itemId={12}
      doc={doc}
      herds={[]}
      canSave
      onDone={vi.fn()}
      addressRequired={addressRequired}
    />,
  );
  fireEvent.change(screen.getByLabelText(/Säljdatum/), {
    target: { value: "2026-10-03" },
  });
}
const type = (label: RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const save = () =>
  screen.getByRole("button", { name: "Spara och nästa" }) as HTMLButtonElement;

describe("SalePanel with a buyer outside the association", () => {
  it("shows the buyer fields and the proof note instead of 'not saved'", () => {
    panel();
    expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    expect(screen.getByLabelText(/Köparens namn/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Ort/)).toBeInTheDocument();
    expect(
      screen.getByText(
        "Ge köparen överlåtelsebeviset. Där står föreningens information till köparen.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/sparas inte/)).toBeNull();
    expect(screen.getByLabelText("Postadress")).toBeInTheDocument();
    expect(screen.queryByLabelText("E-post")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
    expect(screen.getByLabelText("E-post")).toBeInTheDocument();
  });

  it("needs the address from a helper, as the API does (#111)", async () => {
    panel(found(), true);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    type(/Köparens namn/, "Anna Köpare");
    type(/^Ort/, "Visby");
    await new Promise((r) => setTimeout(r, 400)); // the lookup that says it is a new sale
    expect(save().disabled).toBe(true);
    type(/^Postadress/, "Väg 1");
    await waitFor(() => expect(save().disabled).toBe(false));
  });

  it("needs name and town, and sends the buyer with GX1", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    expect(save().disabled).toBe(true);
    type(/Köparens namn/, "Anna Köpare");
    type(/^Ort/, "Visby");
    fireEvent.click(screen.getByRole("checkbox", { name: OPTIN }));
    type(/^Telefon/, "0700000000");
    await waitFor(() => expect(save().disabled).toBe(false)); // once the lookup says it is a new sale
    fireEvent.click(save());
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale).toHaveBeenCalledWith(12, 31, {
      individual: "G9001-2511",
      herd: "GX1",
      date: "2026-10-03",
      buyer: {
        name: "Anna Köpare",
        town: "Visby",
        contact_consent: false,
        membership_optin: true,
        phone: "0700000000",
      },
    });
  });

  it("asks for no buyer on a proof of a sale already registered, wherever it was", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel(registered);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    await waitFor(() =>
      expect(screen.queryByLabelText(/Köparens namn/)).toBeNull(),
    );
    expect(rabbitSales).toHaveBeenCalledWith(12, "G9001-2511");
    expect(save().disabled).toBe(false);
    fireEvent.click(save());
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2]).not.toHaveProperty("buyer");
  });

  it("never hides the buyer on the previous rabbit's sales, and looks up once typing pauses", async () => {
    rabbitSales.mockResolvedValueOnce(registered); // G9001-2511 has the sale
    render(
      <SalePanel itemId={12} doc={doc} herds={[]} canSave onDone={vi.fn()} />,
    );
    fireEvent.change(screen.getByLabelText(/Säljdatum/), {
      target: { value: "2026-10-03" },
    });
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    await waitFor(() =>
      expect(screen.queryByLabelText(/Köparens namn/)).toBeNull(),
    );
    rabbitSales.mockClear();
    rabbitSales.mockResolvedValue(found());
    type(/Individnummer/, "G9001-251");
    type(/Individnummer/, "G9001-2512"); // another rabbit, typed quickly
    expect(screen.getByLabelText(/Köparens namn/)).toBeInTheDocument(); // at once, before any answer
    await waitFor(() => expect(rabbitSales).toHaveBeenCalledTimes(1));
    expect(rabbitSales).toHaveBeenCalledWith(12, "G9001-2512");
  });

  it("asks for the buyer when the rabbit's sale is another one", async () => {
    panel(found({ ...sale, date: "2026-10-04" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    await waitFor(() => expect(rabbitSales).toHaveBeenCalled());
    expect(screen.getByLabelText(/Köparens namn/)).toBeInTheDocument();
  });

  it("asks for and sends the buyer of a registered sale that has none", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel(found({ ...sale, buyer: "none" })); // the legacy form registered it without one
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    await waitFor(() => expect(rabbitSales).toHaveBeenCalled());
    type(/Köparens namn/, "Anna Köpare");
    type(/^Ort/, "Visby");
    await waitFor(() => expect(save().disabled).toBe(false));
    fireEvent.click(save());
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2].buyer).toMatchObject({
      name: "Anna Köpare",
      town: "Visby",
    });
  });

  it("links the proof without a buyer when the sale's buyer was removed", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel(found({ ...sale, buyer: "removed" })); // erased or purged: never asked for again
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    await waitFor(() =>
      expect(screen.queryByLabelText(/Köparens namn/)).toBeNull(),
    );
    fireEvent.click(save());
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2]).not.toHaveProperty("buyer");
  });

  it("says so and saves nothing when the rabbit's sales cannot be read", async () => {
    panel({ ok: false, problem: { status: 404, title: "", detail: "" } });
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    expect(
      await screen.findByText(/Kunde inte läsa kaninens försäljningar/),
    ).toBeInTheDocument();
    type(/Köparens namn/, "Anna Köpare");
    type(/^Ort/, "Visby");
    expect(save().disabled).toBe(true);
  });

  it("sends no buyer for a herd in the association", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel();
    type(/Köparens besättning/, "G9002");
    fireEvent.click(save());
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2]).not.toHaveProperty("buyer");
  });
});
