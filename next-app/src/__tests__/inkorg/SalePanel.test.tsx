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

// 2026 and 2027 ask "Fick köparen försäljningsbeviset?"; before 2026 "Har köparen e-post?"; from 2028 only the bevis (#273).
const BEVIS_DATE = "2028-03-05";
const QUESTION = "Fick köparen försäljningsbeviset?";
const EPOST_QUESTION = "Har köparen e-post?";
const EPOST_DATE = "2025-10-03";

function panel(
  answer: object = found(),
  addressRequired = false,
  date = "2026-10-03",
) {
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
    target: { value: date },
  });
}
const type = (label: RegExp, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const typeEpostBuyer = () => {
  fireEvent.click(
    screen.getByRole("radio", { name: "Nej, men köparen har e-post" }),
  );
  type(/Köparens namn/, "Anna Köpare");
  type(/^Ort/, "Visby");
  type(/^Postadress/, "Väg 1");
  type(/^E-post/, "anna@example.org");
};
const save = () =>
  screen.getByRole("button", { name: "Spara och nästa" }) as HTMLButtonElement;

describe("SalePanel with a buyer outside the association", () => {
  it("shows the buyer fields and the proof note instead of 'not saved' from 2028", () => {
    panel(found(), false, BEVIS_DATE);
    expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    expect(screen.queryByRole("radio")).toBeNull();
    expect(screen.getByLabelText(/Köparens namn/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Ort/)).toBeInTheDocument();
    expect(screen.getByTestId("sell-buyer").className).not.toContain(
      "memberFields",
    ); // the queue keeps its compact fields
    expect(
      screen.getByText(
        "Ge köparen försäljningsbeviset. Där står föreningens information till köparen.",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/sparas inte/)).toBeNull();
    expect(screen.getByLabelText("Postadress")).toBeInTheDocument();
    expect(screen.queryByLabelText("E-post")).toBeNull();
    fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
    expect(screen.getByLabelText("E-post")).toBeInTheDocument();
  });

  it("asks before 2026 whether the buyer has e-mail, and only then for the fields", () => {
    panel(found(), false, EPOST_DATE);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    expect(screen.getByText(EPOST_QUESTION)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
    fireEvent.click(screen.getByRole("radio", { name: "Ja" }));
    expect(screen.getByLabelText(/Köparens namn/)).toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: CONSENT })).toBeNull();
    expect(screen.queryByText(/Ge köparen försäljningsbeviset/)).toBeNull();
  });

  it("needs the address from a helper, as the API does (#111)", async () => {
    panel(found(), true, BEVIS_DATE);
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

  it("needs name and town, and sends the buyer with GX1 (a bevis from 2028)", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel(found(), false, BEVIS_DATE);
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
      date: BEVIS_DATE,
      buyer: {
        name: "Anna Köpare",
        town: "Visby",
        contact_consent: false,
        membership_optin: true,
        phone: "0700000000",
      },
    });
  });

  it("sends the e-mail buyer as notice_only", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel();
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    typeEpostBuyer();
    await waitFor(() => expect(save().disabled).toBe(false));
    fireEvent.click(save());
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2].buyer).toEqual({
      name: "Anna Köpare",
      town: "Visby",
      postal_address: "Väg 1",
      email: "anna@example.org",
      notice_only: true,
    });
  });

  it("asks for no buyer on a proof of a sale already registered, wherever it was", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel(registered);
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    await waitFor(() => expect(screen.queryByText(QUESTION)).toBeNull());
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
    await waitFor(() => expect(screen.queryByText(QUESTION)).toBeNull());
    rabbitSales.mockClear();
    rabbitSales.mockResolvedValue(found());
    type(/Individnummer/, "G9001-251");
    type(/Individnummer/, "G9001-2512"); // another rabbit, typed quickly
    expect(screen.getByText(QUESTION)).toBeInTheDocument(); // at once, before any answer
    await waitFor(() => expect(rabbitSales).toHaveBeenCalledTimes(1));
    expect(rabbitSales).toHaveBeenCalledWith(12, "G9001-2512");
  });

  it("asks for the buyer when the rabbit's sale is another one", async () => {
    panel(found({ ...sale, date: "2026-10-04" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    await waitFor(() => expect(rabbitSales).toHaveBeenCalled());
    expect(screen.getByText(QUESTION)).toBeInTheDocument();
  });

  it("asks for and sends the buyer of a registered sale that has none", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel(found({ ...sale, buyer: "none" })); // the legacy form registered it without one
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    await waitFor(() => expect(rabbitSales).toHaveBeenCalled());
    typeEpostBuyer();
    await waitFor(() => expect(save().disabled).toBe(false));
    fireEvent.click(save());
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2].buyer).toMatchObject({
      name: "Anna Köpare",
      town: "Visby",
      notice_only: true,
    });
  });

  it("links the proof without a buyer when the sale's buyer was removed", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    panel(found({ ...sale, buyer: "removed" })); // erased or purged: never asked for again
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    await waitFor(() => expect(screen.queryByText(QUESTION)).toBeNull());
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
    typeEpostBuyer();
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

// The seller and buyer read off a saved certificate (rule 5 b): made-up names, a reserved domain.
const READ_BUYER = {
  name: "Köpa Testsson",
  postal_address: "Väg 1, 623 55",
  town: "Visby",
  email: "kopa@example.com",
};
function readDoc(sale: object) {
  return {
    ...doc,
    doc_type: "intyg",
    status: "sparad",
    interpretation_status: "klar",
    proposal: {
      fields: {},
      checks: [],
      sale: {
        buyer_herd: null,
        buyer: READ_BUYER,
        date: "2025-06-01",
        seller_herd: "G9002",
        checks: [],
        ...sale,
      },
    },
  } as unknown as InboxDocument;
}
function readPanel(sale: object = {}, changes: object = {}) {
  render(
    <SalePanel
      itemId={12}
      doc={{ ...readDoc(sale), ...changes }}
      herds={[]}
      canSave
      onDone={vi.fn()}
    />,
  );
}
const fillButton = () =>
  screen.getByRole("button", { name: "Fyll i från fotot" });
const value = (label: RegExp) =>
  (screen.getByLabelText(label) as HTMLInputElement).value;

describe("SalePanel with the seller and buyer read off the photo", () => {
  it("lists what was read and fills nothing by itself", () => {
    readPanel({
      checks: [
        {
          ok: false,
          text: "Säljarens besättning G9002 avviker från kaninens ursprungsbesättning G9001.",
        },
      ],
    });
    const read = screen.getByRole("list", { name: "Från fotot" });
    for (const text of [
      "Köpa Testsson",
      "Väg 1, 623 55",
      "Visby",
      "kopa@example.com",
      "2025-06-01",
      "Säljarens besättning: G9002",
    ])
      expect(read).toHaveTextContent(text);
    expect(screen.getByText(/ursprungsbesättning G9001/)).toBeInTheDocument();
    expect(value(/Säljdatum/)).toBe("");
    expect(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    ).not.toBeChecked();
    expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
  });

  it("fills the buyer outside the association, the e-mail for the notice only, on a click", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    readPanel();
    fireEvent.click(fillButton());
    expect(value(/Säljdatum/)).toBe("2025-06-01");
    expect(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    ).toBeChecked();
    expect(screen.getByRole("radio", { name: "Ja" })).toBeChecked(); // before 2026: "Har köparen e-post?"
    expect(value(/Köparens namn/)).toBe("Köpa Testsson");
    expect(value(/^Postadress/)).toBe("Väg 1, 623 55");
    fireEvent.click(
      screen.getByRole("button", { name: "Spara försäljningen" }),
    );
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2]).toEqual({
      individual: "G9001-2511",
      herd: "GX1",
      date: "2025-06-01",
      buyer: { ...READ_BUYER, notice_only: true },
    });
  });

  it("in 2026 and 2027 picks the e-mail for the notice, not the bevis", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    readPanel({ date: "2026-10-03" });
    fireEvent.click(fillButton());
    expect(
      screen.getByRole("radio", { name: "Nej, men köparen har e-post" }),
    ).toBeChecked();
    expect(screen.getByRole("radio", { name: /Ja/ })).not.toBeChecked();
    fireEvent.click(
      screen.getByRole("button", { name: "Spara försäljningen" }),
    );
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2].buyer).toEqual({
      ...READ_BUYER,
      notice_only: true,
    });
    // Saved: Stamboken holds the buyer now. No copy of it is left here, and nothing can send it again.
    expect(
      await screen.findByText("Försäljningen är sparad."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Fyll i från fotot")).toBeNull();
    expect(screen.queryByDisplayValue("Köpa Testsson")).toBeNull();
    expect(screen.queryByDisplayValue("kopa@example.com")).toBeNull();
    expect(screen.queryByRole("button", { name: /Spara/ })).toBeNull();
  });

  it("shows only that the sale is saved when the document already has it", () => {
    readPanel({}, { herd_tracking_id: 7 });
    expect(screen.getByText("Försäljningen är sparad.")).toBeInTheDocument();
    expect(screen.queryByLabelText(/Säljdatum/)).toBeNull();
    expect(screen.queryByRole("button", { name: /Spara|Fyll i/ })).toBeNull();
  });

  it("starts from an empty buyer: nothing typed before stays, no yes and no phone", () => {
    readPanel({ date: BEVIS_DATE });
    fireEvent.change(screen.getByLabelText(/Säljdatum/), {
      target: { value: BEVIS_DATE },
    });
    fireEvent.click(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    );
    fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
    type(/^Telefon/, "0700000000");
    type(/^E-post/, "annan@example.org");
    fireEvent.click(fillButton());
    expect(screen.getByRole("checkbox", { name: CONSENT })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
    expect(value(/^Telefon/)).toBe("");
    expect(value(/^E-post/)).toBe("");
  });

  it("never lets the bevis's yes make the read e-mail a contact address", () => {
    readPanel({ date: "2026-10-03" });
    fireEvent.click(fillButton());
    fireEvent.click(screen.getByRole("radio", { name: "Ja" })); // the buyer got the bevis after all
    fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
    expect(value(/^E-post/)).toBe("");
    fireEvent.click(
      screen.getByRole("radio", { name: "Nej, men köparen har e-post" }),
    );
    expect(value(/^E-post/)).toBe(""); // gone, not kept aside
  });

  it("clears the read e-mail when the date moves to a year without the notice", () => {
    readPanel();
    fireEvent.click(fillButton());
    expect(value(/^E-post/)).toBe("kopa@example.com");
    fireEvent.change(screen.getByLabelText(/Säljdatum/), {
      target: { value: BEVIS_DATE },
    });
    fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
    expect(value(/^E-post/)).toBe("");
  });

  it("asks the handler to choose when the herd read is not the genebank's", () => {
    readPanel({ buyer_herd: { herd: "G9999", found: false } });
    expect(screen.getByRole("list", { name: "Från fotot" })).toHaveTextContent(
      "Köparens besättning: G9999",
    );
    fireEvent.click(fillButton());
    expect(value(/Säljdatum/)).toBe("2025-06-01");
    expect(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    ).not.toBeChecked();
    expect(value(/Köparens besättning/)).toBe("");
    expect(screen.getByRole("status")).toHaveTextContent(
      "finns inte i genbanken",
    );
  });

  it("leaves the choice to the handler when no e-mail was read", () => {
    readPanel({ buyer: { ...READ_BUYER, email: "" } });
    fireEvent.click(fillButton());
    expect(screen.getByRole("radio", { name: "Ja" })).not.toBeChecked();
    expect(screen.queryByLabelText(/Köparens namn/)).toBeNull();
    expect(
      (
        screen.getByRole("button", {
          name: "Spara försäljningen",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: "Ja" }));
    expect(value(/Köparens namn/)).toBe("Köpa Testsson"); // the rest is filled in
    expect(value(/^E-post/)).toBe("");
  });

  it("fills the buyer's herd when it is in Stamboken", () => {
    readPanel({ buyer_herd: { herd: "G9002", found: true } });
    fireEvent.click(fillButton());
    expect(value(/Köparens besättning/)).toBe("G9002");
    expect(
      screen.getByRole("checkbox", { name: "Köparen är utanför föreningen" }),
    ).not.toBeChecked();
  });

  it("from 2028 fills no e-mail and never says yes for the buyer", async () => {
    registerSale.mockResolvedValue({ ok: true, data: { document: doc } });
    readPanel({ date: BEVIS_DATE });
    fireEvent.click(fillButton());
    expect(screen.queryByRole("radio")).toBeNull(); // the bevis is the only way
    expect(screen.getByRole("checkbox", { name: CONSENT })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: OPTIN })).not.toBeChecked();
    fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
    expect(value(/^E-post/)).toBe(""); // a yes ticked by the handler shows an empty field
    fireEvent.click(screen.getByRole("checkbox", { name: CONSENT }));
    fireEvent.click(
      screen.getByRole("button", { name: "Spara försäljningen" }),
    );
    await waitFor(() => expect(registerSale).toHaveBeenCalledTimes(1));
    expect(registerSale.mock.calls[0][2].buyer).toEqual({
      name: "Köpa Testsson",
      town: "Visby",
      postal_address: "Väg 1, 623 55",
      contact_consent: false,
      membership_optin: false,
    });
  });

  it("shows nothing without a finished reading of the sale", () => {
    render(
      <SalePanel itemId={12} doc={doc} herds={[]} canSave onDone={vi.fn()} />,
    );
    expect(screen.queryByText("Fyll i från fotot")).toBeNull();
  });
});
