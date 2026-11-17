import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const actions = vi.hoisted(() => ({
  changeState: vi.fn(),
  checkReportPhoto: vi.fn(),
  confirmMask: vi.fn(),
  reinterpretDocument: vi.fn(),
  takeItem: vi.fn(),
  updateDocument: vi.fn(),
  waitForParent: vi.fn(),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/actions", () => actions);
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
// The canvas needs a browser: a stub that shows the rotation and can turn.
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/[id]/PhotoViewer", () => ({
  PhotoViewer: ({
    rotation,
    onRotate,
  }: {
    rotation: number;
    onRotate: (q: number) => void;
  }) => (
    <div>
      <span data-testid="rotation">{rotation}</span>
      <button onClick={() => onRotate(1)}>Vrid</button>
    </div>
  ),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/[id]/AskBreeder", () => ({
  AskBreeder: () => null,
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/[id]/SalePanel", () => ({
  SalePanel: () => null,
}));
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/CertificateForm",
  () => ({
    CertificateForm: () => null,
  }),
);

import { WorkView } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/WorkView";
import { ModeProvider } from "@/lib/mode-context";
import type {
  InboxDetail,
  InboxDocument,
  QueueUser,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

const helper: QueueUser = { id: 3, is_admin: false, is_manager: null };
const boss: QueueUser = { id: 2, is_admin: false, is_manager: [1] };
const me = { id: 3, name: "Konto 3" };
const other = { id: 9, name: "Konto 9" };

const doc = (changes: Partial<InboxDocument> = {}): InboxDocument => ({
  id: 31,
  status: "sparad",
  mime: "image/jpeg",
  warnings: [],
  duplicates: [],
  doc_type: "intyg",
  cert_format: null,
  rotation: 0,
  mask_rects: null,
  mask_suggestion: null,
  waiting_for: null,
  interpretation_status: "av",
  proposal: null,
  individual: "G9001-2512",
  has_copy: false,
  ...changes,
});

const item = (changes: Partial<InboxDetail> = {}): InboxDetail => ({
  id: 12,
  kind: "upload",
  state: "tagen",
  genebank_id: 1,
  herd: "G9001",
  received_at: "2026-11-14T08:00:00+00:00",
  state_changed_at: "2026-11-14T08:00:00+00:00",
  closed_at: null,
  sender: null,
  assigned_to: me,
  assigned_at: null,
  duplicate_of: null,
  stalled: false,
  missing_proof: false,
  ref_type: null,
  ref_id: null,
  has_message: false,
  maybe_blurry: false,
  sender_authenticated: null,
  sender_address: null,
  message: null,
  documents: [doc()],
  documents_done: 0,
  events: [],
  ...changes,
});

const view = (
  i: InboxDetail,
  user: QueueUser = helper,
  noRole = false,
  reportYear: number | null = null,
) => (
  <ModeProvider mode="prod">
    <WorkView
      item={i}
      user={user}
      noRole={noRole}
      colors={[]}
      herds={[]}
      people={[]}
      reportYear={reportYear}
    />
  </ModeProvider>
);

const ok = (d: InboxDocument) => ({
  ok: true,
  data: { item: item(), document: d },
});

beforeEach(() => {
  for (const f of Object.values(actions)) f.mockReset();
  actions.updateDocument.mockResolvedValue(ok(doc()));
  actions.confirmMask.mockResolvedValue(ok(doc({ status: "klar" })));
});
afterEach(cleanup);

describe("WorkView: masking", () => {
  it("sends the rotation of the turned view with its rectangles in one call", async () => {
    render(view(item()));
    fireEvent.click(screen.getByRole("button", { name: "Vrid" }));
    expect(screen.getByTestId("rotation")).toHaveTextContent("90");
    const confirm = screen.getByRole("button", {
      name: "Bekräfta maskningen och nästa",
    });
    // The turn is saved first; the button waits for it.
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    // The lower third, turned a quarter clockwise with the view: the left third.
    expect(actions.confirmMask).toHaveBeenCalledWith(
      12,
      31,
      90,
      [{ x: 0, y: 0, w: 0.3333, h: 1 }],
      false,
    );
  });

  it("starts from the stored rotation again when the handler changes", () => {
    const { rerender } = render(view(item({ assigned_to: other })));
    // Not the handler: the turn is for reading only and is never saved.
    fireEvent.click(screen.getByRole("button", { name: "Vrid" }));
    expect(screen.getByTestId("rotation")).toHaveTextContent("90");
    expect(actions.updateDocument).not.toHaveBeenCalled();
    rerender(view(item({ assigned_to: me })));
    expect(screen.getByTestId("rotation")).toHaveTextContent("0");
  });

  it("offers 'nothing to hide' only through the checkbox", () => {
    actions.confirmMask.mockClear();
    render(view(item({ documents: [doc({ mask_rects: [] })] })));
    const confirm = screen.getByRole("button", {
      name: "Bekräfta maskningen och nästa",
    });
    expect(confirm).toBeDisabled();
    fireEvent.click(
      screen.getByLabelText("Fotot visar inga säljar- eller köparuppgifter"),
    );
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(actions.confirmMask).toHaveBeenCalledWith(12, 31, 0, [], true);
  });

  it("lets a manager redo the masking of a finished document, from its stored rotation", () => {
    const done = doc({
      status: "klar",
      has_copy: true,
      rotation: 90,
      mask_rects: [{ x: 0.1, y: 0.1, w: 0.2, h: 0.2 }],
    });
    render(
      view(
        item({ state: "klar", assigned_to: other, documents: [done] }),
        boss,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Gör om maskningen" }));
    expect(screen.getByTestId("rotation")).toHaveTextContent("90");
    fireEvent.click(
      screen.getByRole("button", { name: "Bekräfta maskningen och nästa" }),
    );
    expect(actions.confirmMask).toHaveBeenCalledWith(
      12,
      31,
      90,
      [{ x: 0.1, y: 0.1, w: 0.2, h: 0.2 }],
      false,
    );
  });

  it("does not offer the redo to a helper once the item is closed", () => {
    const done = doc({ status: "klar", has_copy: true });
    render(
      view(item({ state: "klar", assigned_to: me, documents: [done] }), helper),
    );
    expect(
      screen.queryByRole("button", { name: "Gör om maskningen" }),
    ).toBeNull();
  });
});

describe("WorkView: an item of a genebank without a role", () => {
  it("says so, and offers no take, state or save buttons", () => {
    render(view(item({ state: "ny", assigned_to: null }), boss, true));
    expect(
      screen.getByText(
        "Du kan läsa det här ärendet men inte spara: du har inte rollen för den här genbanken.",
      ),
    ).toBeInTheDocument();
    for (const name of ["Jag tar den", "Skräp", "Tilldela"])
      expect(screen.queryByRole("button", { name })).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Spara och nästa" }),
    ).toBeNull();
  });
});

describe("WorkView: an annual form", () => {
  const form = doc({ doc_type: "arsblankett", status: "ny", individual: null });

  it("links to the form entry for the round's year, with the item", () => {
    render(view(item({ documents: [form] }), helper, false, 2026));
    expect(
      screen.getByRole("link", { name: "Mata in årsrapporten" }),
    ).toHaveAttribute("href", "/stamboken/arsrapport/G9001/2026?post=12");
  });

  it("leaves the link out without a round, and for someone who cannot save", () => {
    render(view(item({ documents: [form] })));
    expect(
      screen.queryByRole("link", { name: "Mata in årsrapporten" }),
    ).toBeNull();
    cleanup();
    render(view(item({ documents: [form] }), helper, true, 2026));
    expect(
      screen.queryByRole("link", { name: "Mata in årsrapporten" }),
    ).toBeNull();
  });
});

// A certificate photo from the yearly report (4b, G5): already registered, so the reading is set beside the
// registration instead of the masking of a saved certificate. An ordinary saved upload keeps its masking.
describe("WorkView on a report photo", () => {
  const registered = {
    paper_number: "G9001-2511",
    paper_certificate: "P-2511",
    name: "Kulla",
    sex: "female",
    birth_date: "2025-05-10",
    color: null,
    mother: "G9001-24001",
    father: "G9001-24002",
    litter_size: 5,
    litter_size6w: 4,
  };
  // As Flask builds it for a photo read after its rabbit was saved (test_arsrapport_add_rabbit.py,
  // test_every_field_beside_the_registered_rabbit): every field, the paper's own text in `read`.
  const reading = {
    fields: {
      sex: { read: "Hona", value: "female", source: "läst" as const },
      name: {
        read: "Bella",
        value: null,
        source: "avviker" as const,
        registry: "Kulla",
      },
      father: {
        read: "G9001 24002",
        value: "G9001-24002",
        source: "läst" as const,
      },
      mother: {
        read: "G9001 24001",
        value: "G9001-24001",
        source: "läst" as const,
      },
      birth_date: {
        read: "250510",
        value: "2025-05-10",
        source: "läst" as const,
      },
      litter_size: { read: "5", value: 5, source: "läst" as const },
      paper_number: {
        read: "G9001 2511",
        value: "G9001-2511",
        source: "läst" as const,
      },
      litter_size6w: { read: "fyra", value: null, source: "osäker" as const },
      paper_certificate: {
        read: "P-2511",
        value: "P-2511",
        source: "läst" as const,
      },
    },
    checks: [
      { ok: null, text: "G9001-2511 finns redan i Stamboken." },
      {
        ok: false,
        text: "Namnet på intyget är inte registrets för G9001-2511 (Kulla).",
      },
      { ok: true, text: "Intygsnumret är kaninens." },
    ],
  };
  const photoItem = (proposal: InboxDocument["proposal"]) =>
    item({
      kind: "kontroll",
      ref_type: "individual",
      ref_id: 51,
      assigned_to: null,
      state: "ny",
      registered,
      documents: [
        doc({
          individual: "G9001-2511",
          interpretation_status: "klar",
          proposal,
        }),
      ],
    });
  const row = (label: string) =>
    Array.from(
      screen
        .getByRole("table", { name: "Tolkningen och registreringen" })
        .querySelectorAll("tr"),
    ).find((tr) => tr.querySelector("th")?.textContent === label)!;

  it("shows every field read beside the registered rabbit, what differs, what is unsure, and the checks", () => {
    render(view(photoItem(reading)));
    expect(row("Namn")).toHaveAttribute("data-differs", "true");
    expect(row("Namn")).toHaveTextContent("BellaKulla Avviker");
    expect(row("Levande i kullen efter 6 veckor")).toHaveTextContent(
      "fyra (osäker)4",
    );
    expect(row("Levande i kullen efter 6 veckor")).not.toHaveAttribute(
      "data-differs",
    );
    for (const [label, text] of [
      ["Individnummer", "G9001-2511G9001-2511"],
      ["Intygsnummer", "P-2511P-2511"],
      ["Kön", "HonaHona"],
      ["Födelsedatum", "2025-05-102025-05-10"],
      ["Mor", "G9001-24001G9001-24001"],
      ["Far", "G9001-24002G9001-24002"],
      ["Antal födda", "55"],
    ]) {
      expect(row(label)).toHaveTextContent(text);
      expect(row(label)).not.toHaveAttribute("data-differs");
    }
    expect(row("Färg")).toHaveTextContent("––");
    const checks = screen.getByRole("list", { name: "Kontroller" });
    expect(checks).toHaveTextContent(
      "✗ Namnet på intyget är inte registrets för G9001-2511 (Kulla).",
    );
    expect(checks).toHaveTextContent("✓ Intygsnumret är kaninens.");
    expect(screen.getByRole("link", { name: "G9001-2511" })).toBeVisible();
    expect(screen.queryByText("Dölj säljare och köpare")).toBeNull();
  });

  it("a value read before the rabbit was saved is compared with what was registered", () => {
    render(
      view(
        photoItem({
          fields: { name: { value: "Kalla", source: "läst", read: "Kalla" } },
          checks: [],
        }),
      ),
    );
    expect(row("Namn")).toHaveAttribute("data-differs", "true");
    expect(row("Namn")).toHaveTextContent("KallaKulla Avviker");
    expect(screen.queryByRole("list", { name: "Kontroller" })).toBeNull();
  });

  it("an ordinary saved certificate still opens the masking", () => {
    render(view(item({ registered: null })));
    expect(screen.getByText("Dölj säljare och köpare")).toBeInTheDocument();
    expect(
      screen.queryByRole("table", { name: "Tolkningen och registreringen" }),
    ).toBeNull();
  });
});

// Closing a report photo: its handler compares and closes it, or has it read again (4b).
describe("ReportPhotoCheck's buttons", () => {
  const photoItem = (changes: Partial<InboxDetail> = {}) =>
    item({
      kind: "kontroll",
      ref_type: "individual",
      ref_id: 51,
      registered: { paper_number: "G9001-2511", name: "Kulla" },
      documents: [doc({ status: "sparad", interpretation_status: "klar" })],
      ...changes,
    });

  beforeEach(() => {
    actions.reinterpretDocument.mockResolvedValue({ ok: true, data: {} });
  });

  it("for the handler: Stämmer and Rättat close it, Tolka igen reads it again", async () => {
    const checkReportPhoto = vi.mocked(actions.checkReportPhoto);
    checkReportPhoto.mockResolvedValue({ ok: true, data: {} });
    render(view(photoItem()));
    // one at a time: the buttons wait while a call is out
    const press = async (name: string) => {
      const button = screen.getByRole("button", { name });
      await waitFor(() => expect(button).toBeEnabled());
      fireEvent.click(button);
    };
    await press("Stämmer");
    await waitFor(() =>
      expect(checkReportPhoto).toHaveBeenCalledWith(12, 31, "stammer"),
    );
    await press("Rättat");
    await waitFor(() =>
      expect(checkReportPhoto).toHaveBeenCalledWith(12, 31, "rattat"),
    );
    await press("Tolka igen");
    await waitFor(() =>
      expect(actions.reinterpretDocument).toHaveBeenCalledWith(12, 31),
    );
  });

  it("before it is taken: no closing, and the take button where the note is", () => {
    render(view(photoItem({ assigned_to: null, state: "ny" }), boss));
    expect(screen.queryByRole("button", { name: "Stämmer" })).toBeNull();
    expect(screen.getAllByRole("button", { name: "Jag tar den" }).length).toBe(
      2,
    ); // the header and the note
  });

  it("checked or closed: no buttons", () => {
    render(
      view(
        photoItem({
          state: "klar",
          documents: [doc({ status: "klar", interpretation_status: "klar" })],
        }),
      ),
    );
    expect(screen.queryByRole("button", { name: "Stämmer" })).toBeNull();
    expect(screen.getByText("Ärendet är stängt.")).toBeInTheDocument();
  });
});

describe("WorkView: a sale proposal", () => {
  const proposal = item({
    kind: "kontroll",
    state: "ny",
    assigned_to: null,
    ref_type: "sale_proposal",
    ref_id: 7,
    documents: [],
    report_year: 2025,
  });

  it("links to its own round's status view, not the newest round's", () => {
    render(view(proposal, boss, false, 2026)); // 2026 is the newest round the genebank activated
    expect(screen.getByText(/Avgörs i årsrapportens statusvy/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Öppna statusvyn" }),
    ).toHaveAttribute(
      "href",
      "/stamboken/arsrapport/status/2025?genebank_id=1",
    );
  });

  it("keeps the text without a year", () => {
    render(view({ ...proposal, report_year: null }, boss, false, 2026));
    expect(screen.getByText(/Avgörs i årsrapportens statusvy/)).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Öppna statusvyn" })).toBeNull();
  });
});

describe("WorkView: a bought rabbit's sent photos (S7)", () => {
  it("shows the purchase beside an ordinary upload, which the queue works on", () => {
    const sent = item({
      kind: "upload",
      state: "ny",
      assigned_to: null,
      herd: "G9001",
      documents: [doc({ doc_type: "intyg", status: "ny" })],
      ref_data: {
        number: "G9002-2511",
        from_herd: "G9002",
        date: "2025-05-14",
      },
    });
    render(view(sent, boss, false, 2026));
    expect(
      screen.getByText(/Köpt av G9001: G9002-2511 från G9002, 14 maj 2025/),
    ).toBeTruthy();
    expect(screen.queryByText(/Ärendet gäller/)).toBeNull();
    expect(screen.queryByText(/Anmält köp/)).toBeNull();
  });
});

describe("WorkView: a purchase notice (4a Task 5)", () => {
  const notice = item({
    kind: "kontroll",
    state: "ny",
    assigned_to: null,
    ref_type: "kopanmalan",
    ref_id: null,
    documents: [],
    report_year: null,
    ref_data: {
      number: "G9002-2501",
      from_herd: "G9002",
      date: "2025-05-14",
      individual_id: 70,
    },
  });

  it("shows its fields and the rabbit's page, where the sale is registered", () => {
    render(view(notice, boss, false, 2026));
    expect(
      screen.getByText(/Anmält köp: G9002-2501 från G9002, 14 maj 2025/),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "kaninens sida" })).toHaveAttribute(
      "href",
      "/stamboken/individ/G9002-2501",
    );
    expect(screen.queryByRole("link", { name: "Öppna statusvyn" })).toBeNull();
  });

  it("names the link that sent it in the history", () => {
    const event = {
      id: 1,
      at: "2026-01-10T11:00:00+00:00",
      kind: "inkommen",
      user: null,
      detail: { via: "länk G9001/2025" },
    };
    render(view({ ...notice, events: [event] }, boss, false, 2026));
    expect(screen.getByText(/Inkommet via länk G9001\/2025/)).toBeTruthy();
  });

  it("shows a photo sent with it, and nothing to work on from it in the queue", () => {
    render(
      view(
        { ...notice, documents: [doc({ doc_type: "bevis", status: "ny" })] },
        boss,
        false,
        2026,
      ),
    );
    expect(screen.getByText(/Anmält köp: G9002-2501/)).toBeTruthy();
    expect(screen.queryByText(/Ärendet gäller kopanmalan/)).toBeNull();
    expect(screen.queryByText("Försäljning")).toBeNull(); // the queue's sale panel
  });

  it("lets its handler look at the photo and dismiss it, never retype or read it", () => {
    const photo = doc({
      doc_type: "intyg",
      status: "ny",
      individual: null,
      interpretation_status: "klar",
    });
    const taken = { ...notice, state: "tagen" as const, assigned_to: me };
    render(view({ ...taken, documents: [photo] }, helper, false, 2026));
    expect(screen.getByRole("button", { name: "Avfärda" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Vrid" })).toBeTruthy();
    expect(screen.queryByLabelText("Typ")).toBeNull();
    expect(screen.queryByLabelText("Format")).toBeNull();
    expect(screen.queryByRole("button", { name: "Tolka igen" })).toBeNull();
    cleanup(); // the same photo in an upload offers them
    render(view(item({ documents: [photo] }), helper));
    expect(screen.getByLabelText("Typ")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Tolka igen" })).toBeTruthy();
  });

  it("links to the status view when a pending sale matches it", () => {
    render(view({ ...notice, report_year: 2025 }, boss, false, 2026));
    expect(
      screen.getByRole("link", { name: "Öppna statusvyn" }),
    ).toHaveAttribute(
      "href",
      "/stamboken/arsrapport/status/2025?genebank_id=1",
    );
  });
});
