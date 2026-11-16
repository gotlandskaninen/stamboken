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
