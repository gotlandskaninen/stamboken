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
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/actions", () => ({
  registerSale: (...args: unknown[]) => registerSale(...args),
}));

import { SalePanel } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/SalePanel";
import type { InboxDocument } from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

beforeAll(async () => {
  await import("@/i18n");
});

afterEach(() => {
  cleanup();
  registerSale.mockReset();
});

const CONSENT =
  "Köparen har kryssat ja: föreningen får spara adress, e-post och telefon så länge köparen har kaninen";
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

function panel() {
  render(
    <SalePanel itemId={12} doc={doc} herds={[]} canSave onDone={vi.fn()} />,
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
    expect(screen.queryByLabelText("Postadress")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
    expect(screen.getByLabelText("Postadress")).toBeInTheDocument();
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
    expect(save().disabled).toBe(false);
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

  it("sends no buyer for a herd in the association", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel();
    type(/Köparens besättning/, "G9002");
    fireEvent.click(save());
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2]).not.toHaveProperty("buyer");
  });
});
