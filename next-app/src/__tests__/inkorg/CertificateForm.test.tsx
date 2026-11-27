import "@testing-library/jest-dom/vitest";
import "@/i18n";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/actions", () => ({
  lookupRabbit: vi.fn(async () => null),
  reconcileDocument: vi.fn(async () => null),
  saveCertificate: vi.fn(),
}));

import { CertificateForm } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/CertificateForm";
import {
  reconcileDocument,
  saveCertificate,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/actions";
import type {
  InboxDocument,
  Proposal,
  Reconciliation,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

afterEach(() => {
  cleanup();
  vi.mocked(saveCertificate).mockReset();
  vi.mocked(reconcileDocument).mockReset();
  vi.mocked(reconcileDocument).mockResolvedValue(null);
});

// A synthetic reading: the number read, the mother one character off, the
// father's branch against the registry, the birth date unreadable.
const PROPOSAL: Proposal = {
  fields: {
    paper_number: { value: "G9001-2511", source: "läst", read: "G9001 2511" },
    mother: { value: "G9001-2211", source: "härlett", read: "G9OO1 2211" },
    father: { value: null, source: "avviker", read: "G9002 2311" },
    birth_date: { value: null, source: "osäker", read: "10/5" },
    farfar: {
      value: null,
      source: "avviker",
      read: "G9003 2011",
      registry: "G9002-2011",
    },
  },
  checks: [
    { ok: true, text: "Intygsnumret är ledigt." },
    {
      ok: false,
      text: "Far: far- och morföräldrarna på intyget är inte registrets för G9002-2311.",
    },
  ],
};

const doc = (changes: Partial<InboxDocument> = {}): InboxDocument => ({
  id: 31,
  status: "ny",
  mime: "image/jpeg",
  warnings: [],
  duplicates: [],
  doc_type: "intyg",
  cert_format: null,
  rotation: 0,
  mask_rects: null,
  mask_suggestion: null,
  waiting_for: null,
  interpretation_status: "klar",
  proposal: PROPOSAL,
  individual: null,
  has_copy: false,
  ...changes,
});

const form = (d: InboxDocument, onSaved = () => undefined) => (
  <CertificateForm
    itemId={12}
    doc={d}
    colors={["viltgrå"]}
    canSave
    onSaved={onSaved}
    onSkip={() => undefined}
  />
);
const show = (d: InboxDocument) => render(form(d));

const input = (label: RegExp) => screen.getByLabelText(label);
const sourceOf = (label: RegExp) =>
  input(label).closest("[data-source]")?.getAttribute("data-source") ?? null;

describe("CertificateForm with the image reading's proposal", () => {
  it("prefills läst and härlett, leaves avviker and osäker empty", () => {
    show(doc());
    expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-2511");
    expect(input(/^Mor/)).toHaveValue("G9001-2211");
    expect(input(/^Far(?!-)/)).toHaveValue("");
    expect(input(/^Födelsedatum/)).toHaveValue("");
  });

  it("says why a photo too small was not read, and that Tolka igen reads it", () => {
    const small = doc({ proposal: null, interpretation_status: "for_litet" });
    show(small);
    expect(
      screen.getByText(/för litet för att tolkas av sig självt/),
    ).toHaveTextContent("klicka Tolka igen");
    cleanup();
    // Someone who only reads the item gets the reason, not a button they lack.
    render(
      <CertificateForm
        itemId={12}
        doc={small}
        colors={[]}
        canSave={false}
        onSaved={() => undefined}
        onSkip={() => undefined}
      />,
    );
    expect(
      screen.getByText(/för litet för att tolkas av sig självt/),
    ).not.toHaveTextContent("Tolka igen");
  });

  it("keeps the queue's compact look: Kön a menu, not the member's choices", () => {
    show(doc({ proposal: null, interpretation_status: "vantar" }));
    const form = input(/^Namn/).closest("form")!;
    expect(form.className).not.toContain("memberFields");
    expect(screen.getByRole("combobox", { name: /^Kön/ })).toBeTruthy();
    expect(screen.queryByRole("group", { name: "Kön" })).toBeNull();
  });

  it("keeps the queue's hint for the count at 6 weeks: the queue asks for it", () => {
    show(doc({ proposal: null, interpretation_status: "vantar" }));
    expect(screen.getByText("Står inte alltid på intyget.")).toBeTruthy();
    expect(screen.queryByText(/lämna tomt/)).toBeNull();
  });

  it("colours each field by its source and shows what was read", () => {
    show(doc());
    expect(sourceOf(/^Individnummer på pappret/)).toBe("läst");
    expect(sourceOf(/^Mor/)).toBe("härlett");
    expect(sourceOf(/^Far(?!-)/)).toBe("avviker");
    expect(sourceOf(/^Födelsedatum/)).toBe("osäker");
    expect(sourceOf(/^Intygsnummer/)).toBeNull();
    expect(screen.getByText("Inläst: G9002 2311")).toBeInTheDocument();
    expect(
      screen.getByText("Inläst: G9003 2011 · Registret: G9002-2011"),
    ).toBeInTheDocument();
  });

  it("does not caption a number read with how to write it", () => {
    show(doc());
    expect(screen.getByText("Som det står på intyget.")).toBeInTheDocument();
    cleanup();
    const unsure = {
      ...PROPOSAL,
      fields: {
        ...PROPOSAL.fields,
        paper_number: {
          value: null,
          source: "osäker" as const,
          read: "G9001 2511",
        },
      },
    };
    show(doc({ proposal: unsure }));
    expect(screen.getByText("Inläst: G9001 2511")).toBeInTheDocument();
    expect(screen.queryByText(/Som det står på intyget/)).toBeNull();
  });

  it("lists the checks under the form, with the note to compare with the photo", () => {
    show(doc());
    const checks = screen.getByRole("list", { name: "Kontroller" });
    const lines = within(checks).getAllByRole("listitem");
    expect(lines.map((li) => li.getAttribute("data-ok"))).toEqual([
      "true",
      "false",
    ]);
    expect(checks).toHaveTextContent("Intygsnumret är ledigt.");
    expect(screen.getByText(/Jämför varje fält med fotot/)).toBeInTheDocument();
    expect(
      screen.getByText(/räknas inte om när du skriver/),
    ).toBeInTheDocument();
  });

  it("opens on the paper certificate when the rabbit is in Stamboken", () => {
    const found: Proposal = {
      fields: { individual: { value: "G9001-2411", source: "läst" } },
      checks: [
        { ok: true, text: "G9001-2411 finns redan med digitalt intyg." },
      ],
    };
    show(doc({ proposal: found }));
    expect(
      screen.getByRole("button", {
        name: "Pappersintyg på en kanin som finns",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(input(/^Individnummer i Stamboken/)).toHaveValue("G9001-2411");
  });

  it("while the photo is read, or when it failed, the form is empty", () => {
    show(doc({ interpretation_status: "vantar", proposal: null }));
    expect(screen.getByText(/Fotot tolkas/)).toBeInTheDocument();
    expect(input(/^Individnummer på pappret/)).toHaveValue("");
    cleanup();
    show(doc({ interpretation_status: "misslyckad" }));
    expect(screen.getByText(/Fotot gick inte att tolka/)).toBeInTheDocument();
    expect(input(/^Mor/)).toHaveValue("");
    expect(screen.queryByRole("list", { name: "Kontroller" })).toBeNull();
  });
});

describe("CertificateForm when the reading finishes while it is open", () => {
  const reading = () =>
    doc({ interpretation_status: "vantar", proposal: null });

  it("never replaces what the handler typed: it offers the proposal", () => {
    const { rerender } = show(reading());
    fireEvent.change(input(/^Individnummer på pappret/), {
      target: { value: "G9001-9999" },
    });
    rerender(form(doc()));
    expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-9999");
    expect(
      screen.getByText(/Det finns ett förslag från tolkningen/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fyll i förslaget" }));
    expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-2511");
    expect(screen.queryByText(/Det finns ett förslag/)).toBeNull();
  });

  it("fills an untouched form with the proposal at once", () => {
    const { rerender } = show(reading());
    rerender(form(doc()));
    expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-2511");
    expect(screen.queryByText(/Det finns ett förslag/)).toBeNull();
  });
});

// The form moved to RegisterFromCertificate (4b): the queue's save is unchanged.
describe("CertificateForm saves as before the move", () => {
  const fillRest = () => {
    fireEvent.change(input(/^Intygsnummer/), { target: { value: "P-1" } });
    fireEvent.change(input(/^Far(?!-)/), { target: { value: "g9002-2311" } });
    fireEvent.change(input(/^Födelsedatum/), {
      target: { value: "2025-05-10" },
    });
  };
  const NEW_RABBIT = {
    action: "ny_kanin",
    paper_number: "G9001-2511",
    paper_certificate: "P-1",
    mother: "G9001-2211",
    father: "G9002-2311",
    birth_date: "2025-05-10",
    rex: false, // main's rex choice, sent with every new rabbit
  };

  it("posts the item's document with the form's payload, and hands on the saved document", async () => {
    const saved = doc({ individual: "G9001-2511" } as Partial<InboxDocument>);
    vi.mocked(saveCertificate).mockResolvedValue({
      ok: true,
      data: { item: {} as never, document: saved },
    });
    const onSaved = vi.fn();
    render(form(doc(), onSaved));
    fillRest();
    fireEvent.click(screen.getByRole("button", { name: "Spara och nästa" }));
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith(saved));
    expect(saveCertificate).toHaveBeenCalledWith(12, 31, NEW_RABBIT);
  });

  it("a number conflict opens the dialog, and Pappret rättas sends Stamboken's number", async () => {
    vi.mocked(saveCertificate)
      .mockResolvedValueOnce({
        ok: false,
        problem: {
          status: 409,
          title: "number_conflict",
          detail:
            "Individnumret på pappersintyget stämmer inte med Stambokens.",
          extensions: {
            check_status: "conflict",
            stamboken_number: "G9001-2511",
            paper_number: "G9001-2521",
            conflicts: [
              { kind: "litter", paper: "2", stamboken: "1", holder: null },
            ],
            choices: ["use_stamboken_number", "paper_is_right"],
            actions: [],
          },
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { item: {} as never, document: doc() },
      });
    show(doc());
    fillRest();
    fireEvent.click(screen.getByRole("button", { name: "Spara och nästa" }));
    const corrected = await screen.findByRole("button", {
      name: "Pappret rättas",
    });
    await waitFor(() => expect(corrected).toBeEnabled()); // the first save has finished
    fireEvent.click(corrected);
    await waitFor(() => expect(saveCertificate).toHaveBeenCalledTimes(2));
    expect(vi.mocked(saveCertificate).mock.calls[1][2]).toEqual({
      ...NEW_RABBIT,
      resolution: {
        expected_number: "G9001-2511",
        choice: "use_stamboken_number",
      },
    });
    // the refusal stood next to the paper's number, with the queue's hint
    expect(
      screen.getByText("Stämmer pappret? Lämna ärendet till genbanksansvarig."),
    ).toBeInTheDocument();
  });
});

// A rabbit in Stamboken: its number read but unsure, the paper's number and
// certificate read.
const FOUND: Proposal = {
  fields: {
    individual: { value: null, source: "osäker", read: "G9001 2411" },
    paper_number: { value: "G9001-2411", source: "läst", read: "G9001 2411" },
    paper_certificate: { value: "SYN-777", source: "läst", read: "SYN 777" },
  },
  checks: [],
};
const ANSWER: Reconciliation = {
  rows: {
    individual: { registry: null, status: "osaker" },
    paper_number: { registry: "G9001-2411", status: "stammer" },
    paper_certificate: { registry: "SYN-778", status: "skiljer" },
    name: { registry: "Elsa", status: "ingen" },
    sex: { registry: "female", status: "ingen" },
  },
  checks: [
    { ok: false, text: "G9001-2411 har redan intyg SYN-778 i Stamboken." },
  ],
};
const ALL_ROWS = [
  "Individnummer på pappret",
  "Intygsnummer",
  "Namn",
  "Kön",
  "Födelsedatum",
  "Färg",
  "Antal födda",
  "Levande efter 6 veckor",
  "Mor",
  "Morfar",
  "Mormor",
  "Far",
  "Farfar",
  "Farmor",
];

const rowOf = (label: string) => screen.getByLabelText(label).closest("tr")!;
const registryOf = (label: string) =>
  rowOf(label).querySelector('[data-label="Registret"]');
const type = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
const wait = (ms: number) => act(() => vi.advanceTimersByTimeAsync(ms));

describe("CertificateForm's table for a rabbit in Stamboken", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("shows every row beside the registry, with what was read and a status in words", async () => {
    vi.mocked(reconcileDocument).mockResolvedValue(ANSWER);
    show(doc({ proposal: FOUND }));
    await wait(250);
    for (const label of ["Individnummer i Stamboken", ...ALL_ROWS])
      expect(screen.getByLabelText(label)).toBeInTheDocument();
    expect(rowOf("Intygsnummer")).toHaveTextContent("SYN 777"); // Inläst
    expect(screen.getByLabelText("Intygsnummer")).toHaveValue("SYN-777");
    expect(registryOf("Intygsnummer")).toHaveTextContent("SYN-778");
    expect(within(rowOf("Intygsnummer")).getByText("skiljer sig")).toBeTruthy();
    expect(
      within(rowOf("Individnummer på pappret")).getByText("stämmer"),
    ).toBeTruthy();
    expect(registryOf("Kön")).toHaveTextContent("Hona");
    expect(within(rowOf("Namn")).getByText("inget att jämföra")).toBeTruthy();
    expect(registryOf("Farmor")).toHaveTextContent("–");
    expect(
      screen.getByText(
        "1 stämmer · 1 osäker · 1 skiljer sig · 2 utan jämförelse",
      ),
    ).toBeInTheDocument();
    const checks = screen.getByRole("list", { name: "Kontroller" });
    expect(checks).toHaveTextContent("har redan intyg SYN-778");
    expect(screen.queryByText(/räknas inte om/)).toBeNull();
  });

  it("asks again 250 ms after the last change, with every row as typed", async () => {
    show(doc({ proposal: FOUND }));
    await wait(250);
    expect(reconcileDocument).toHaveBeenCalledTimes(1);
    expect(reconcileDocument).toHaveBeenLastCalledWith(
      12,
      31,
      expect.objectContaining({
        mode: "pappersintyg",
        individual: "",
        paper_number: "G9001-2411",
        paper_certificate: "SYN-777",
        morfar: "",
      }),
    );
    type("Individnummer i Stamboken", "G9001-241");
    await wait(200);
    type("Individnummer i Stamboken", "G9001-2411");
    type("Morfar", "G9004-2011");
    await wait(249);
    expect(reconcileDocument).toHaveBeenCalledTimes(1);
    await wait(1);
    expect(reconcileDocument).toHaveBeenCalledTimes(2);
    expect(reconcileDocument).toHaveBeenLastCalledWith(
      12,
      31,
      expect.objectContaining({
        individual: "G9001-2411",
        morfar: "G9004-2011",
      }),
    );
  });

  it("drops an answer to an earlier request", async () => {
    let late: (answer: Reconciliation) => void = () => undefined;
    vi.mocked(reconcileDocument)
      .mockImplementationOnce(() => new Promise((answer) => (late = answer)))
      .mockResolvedValueOnce(ANSWER);
    show(doc({ proposal: FOUND }));
    await wait(250);
    type("Namn", "Elsa");
    await wait(250);
    expect(registryOf("Namn")).toHaveTextContent("Elsa");
    await act(async () =>
      late({
        rows: { name: { registry: "Lova", status: "skiljer" } },
        checks: [],
      }),
    );
    expect(registryOf("Namn")).toHaveTextContent("Elsa");
  });

  it("offers the numbers one character off, and one fills the field", async () => {
    vi.mocked(reconcileDocument).mockResolvedValue({
      rows: {
        individual: {
          registry: "finns inte",
          status: "skiljer",
          near: [{ number: "G9001-2411", name: "Elsa", sex: "female" }],
        },
      },
      checks: [],
    });
    show(doc({ proposal: FOUND }));
    type("Individnummer i Stamboken", "G9011-2411");
    await wait(250);
    expect(screen.getByText("Menar du:")).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "G9001-2411 Elsa (hona)" }),
    );
    expect(screen.getByLabelText("Individnummer i Stamboken")).toHaveValue(
      "G9001-2411",
    );
  });

  it("Ta inläst fills an osäker row with what was read, as the registry writes it", async () => {
    vi.mocked(reconcileDocument).mockResolvedValue(ANSWER);
    show(doc({ proposal: FOUND }));
    await wait(250);
    // only the osäker row offers it
    expect(screen.getAllByRole("button", { name: /^Ta inläst/ })).toHaveLength(
      1,
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "Ta inläst: Individnummer i Stamboken",
      }),
    );
    expect(screen.getByLabelText("Individnummer i Stamboken")).toHaveValue(
      "G9001-2411",
    );
  });
});

describe("CertificateForm saves a paper certificate as before the table", () => {
  it("sends the rabbit, the paper's number and the certificate, nothing compared only", async () => {
    vi.mocked(saveCertificate).mockResolvedValue({
      ok: true,
      data: { item: {} as never, document: doc() },
    });
    show(doc({ proposal: FOUND }));
    type("Individnummer i Stamboken", "g9001-2411");
    type("Namn", "Elsa");
    type("Morfar", "G9004-2011");
    fireEvent.click(screen.getByRole("button", { name: "Spara och nästa" }));
    await waitFor(() => expect(saveCertificate).toHaveBeenCalled());
    expect(saveCertificate).toHaveBeenCalledWith(12, 31, {
      action: "pappersintyg",
      individual: "G9001-2411",
      paper_certificate: "SYN-777",
      paper_number: "G9001-2411",
    });
  });

  it("places a refusal at its row", async () => {
    vi.mocked(saveCertificate).mockResolvedValue({
      ok: false,
      problem: {
        status: 409,
        title: "Konflikt",
        detail: "Intygsnumret SYN-777 används redan.",
        extensions: { field: "paper_certificate" },
      },
    });
    show(doc({ proposal: FOUND }));
    type("Individnummer i Stamboken", "G9001-2411");
    fireEvent.click(screen.getByRole("button", { name: "Spara och nästa" }));
    await screen.findByText("Intygsnumret SYN-777 används redan.");
    expect(rowOf("Intygsnummer")).toHaveTextContent("används redan");
    expect(screen.getByLabelText("Intygsnummer")).toHaveAttribute(
      "aria-invalid",
      "true",
    );
  });
});
