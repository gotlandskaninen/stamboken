import "@/i18n";
import "@testing-library/jest-dom/vitest";
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

const actions = vi.hoisted(() => ({
  changeState: vi.fn(),
  checkReportPhoto: vi.fn(),
  confirmMask: vi.fn(),
  findPaper: vi.fn(),
  reinterpretDocument: vi.fn(),
  takeItem: vi.fn(),
  undoAssignment: vi.fn(),
  updateDocument: vi.fn(),
  waitForParent: vi.fn(),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/actions", () => actions);
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
// The canvas needs a browser: a stub that shows the rotation and the angle and
// can turn and straighten, and a button per rectangle on the photo that selects
// it (Delete removes it).
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/[id]/PhotoViewer", () => ({
  PhotoViewer: ({
    rotation,
    onRotate,
    straighten,
    onStraighten,
    straightenLocked,
    onFindPaper,
    mask,
  }: {
    rotation: number;
    onRotate: (q: number) => void;
    straighten: number;
    onStraighten: (d: number) => void;
    straightenLocked: boolean;
    onFindPaper?: () => void;
    mask?: MaskLayer;
  }) => (
    <div>
      <span data-testid="rotation">{rotation}</span>
      <span data-testid="straighten">{straighten}</span>
      <button onClick={() => onRotate(1)}>Vrid</button>
      <button disabled={straightenLocked} onClick={() => onStraighten(4)}>
        Räta
      </button>
      {onFindPaper && <button onClick={onFindPaper}>Hitta pappret</button>}
      {mask?.rects.map((_, i) => (
        <button
          key={i}
          aria-pressed={mask.selected === i}
          onClick={() => mask.onSelect(i)}
          onKeyDown={(e) => e.key === "Delete" && mask.onRemove(i)}
        >
          {i === mask.frameAt ? "Ramen" : `Ruta ${i}`}
        </button>
      ))}
    </div>
  ),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/[id]/AskBreeder", () => ({
  AskBreeder: ({
    documentId,
    crop,
    turn,
    onFrame,
  }: {
    documentId: number | null;
    crop: unknown;
    turn: { rotation: number; straighten: number } | null;
    onFrame: (on: boolean) => void;
  }) => (
    <div>
      {turn && (
        <span data-testid="turn">{`${turn.rotation}:${turn.straighten}`}</span>
      )}
      {documentId !== null && (
        <button onClick={() => onFrame(true)}>Bifoga utsnitt</button>
      )}
      {crop ? <span>Utsnittet är ritat</span> : null}
    </div>
  ),
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
import type { MaskLayer } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/PhotoViewer";
import { UPPER_TWO_THIRDS } from "@/app/(app)/stamboken/(dashboard)/inkorg/image";
import { QueueUndoProvider } from "@/app/(app)/stamboken/(dashboard)/inkorg/QueueUndo";
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
  straighten: 0,
  mask_rects: null,
  copy_frame: null,
  frame_suggestion: null,
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
  mentioned_individuals: [],
  documents: [doc()],
  documents_done: 0,
  events: [],
  ...changes,
});

const view = (
  i: InboxDetail,
  user: QueueUser = helper,
  noRole = false,
  reportYears: number[] = [],
) => (
  <ModeProvider mode="prod">
    <QueueUndoProvider>
      <WorkView
        item={i}
        user={user}
        noRole={noRole}
        colors={[]}
        herds={[]}
        people={[]}
        reportYears={reportYears}
      />
    </QueueUndoProvider>
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

describe("WorkView: mail", () => {
  it("can undo a takeover started in the registration view", async () => {
    actions.takeItem.mockResolvedValue({
      ok: true,
      data: { undo: "takeover" },
    });
    actions.undoAssignment.mockResolvedValue({
      ok: true,
      data: { restored: [12] },
    });
    const assigned_at = "2026-11-14T08:00:00.123456+00:00";
    render(
      <main>
        <h1>Ärende 12</h1>
        {view(item({ assigned_to: other, assigned_at, documents: [] }))}
      </main>,
    );
    const heading = screen.getByRole("heading", { name: "Ärende 12" });
    expect(heading).toHaveFocus();
    screen.getByRole("button", { name: "Ta över" }).focus();
    fireEvent.click(screen.getByRole("button", { name: "Ta över" }));
    expect(
      await screen.findByText("Du har tagit över ärende 12."),
    ).toBeVisible();
    expect(heading).toHaveFocus();
    fireEvent.click(await screen.findByRole("button", { name: "Ångra" }));
    expect(actions.takeItem).toHaveBeenCalledWith(12, {
      assigned_to: other.id,
      assigned_at,
    });
    expect(actions.undoAssignment).toHaveBeenCalledWith("takeover");
    await screen.findByText("Ändringen har ångrats.");
  });
  it.each([false, true])("shows the message with documents=%s", (hasDoc) => {
    render(
      view(
        item({
          kind: hasDoc ? "mail" : "meddelande",
          state: "ny",
          assigned_to: null,
          sender_address: "inkorg@example.org",
          message: "Här är intyget.",
          events: [
            {
              id: 1,
              kind: "inkommen",
              at: "2026-11-24T10:00:00Z",
              user: null,
              detail: {
                subject: "Intyg",
                not_saved: ["bilaga_till_intyget_20260101.png"],
              },
            },
            {
              id: 2,
              kind: "svar",
              at: "2026-11-24T11:00:00Z",
              user: null,
              detail: { text: "Här är kompletteringen." },
            },
          ],
          documents: hasDoc ? [doc()] : [],
        }),
        boss,
      ),
    );
    const mail = screen.getByRole("region", { name: "Meddelande" });
    expect(within(mail).getByText("Intyg")).toBeVisible();
    expect(within(mail).getByText("Här är intyget.")).toBeVisible();
    expect(within(mail).getByText("Här är kompletteringen.")).toBeVisible();
    const facts = within(
      screen.getByRole("complementary", { name: "Ärendet" }),
    );
    expect(facts.getByText("inkorg@example.org")).toBeVisible();
    expect(facts.getByText("bilaga_till_intyget_20260101.png")).toBeVisible();
    expect(facts.getByText(/· Svar inkommet$/)).toBeInTheDocument();
    expect(facts.queryByText(/Här är kompletteringen/)).toBeNull();
    for (const name of ["Jag tar den", "Tilldela"]) {
      const button = facts.getByRole("button", { name });
      expect(button).toHaveClass("sb-btn");
      expect(button).not.toHaveClass("sb-btn-sm");
    }
    for (const name of ["Fotot", "Registrering"])
      expect(!!screen.queryByRole("region", { name })).toBe(hasDoc);
    expect(!!facts.queryByRole("heading", { name: "Dokument" })).toBe(hasDoc);
  });
});

describe("WorkView: masking", () => {
  it("sends the rotation of the turned view with its frame and rectangles in one call", async () => {
    const handwritten = doc({
      cert_format: "handskrivet",
      frame_suggestion: UPPER_TWO_THIRDS,
    });
    render(view(item({ documents: [handwritten] })));
    fireEvent.click(screen.getByRole("button", { name: "Lägg till ruta" }));
    fireEvent.click(screen.getByRole("button", { name: "Vrid" }));
    expect(screen.getByTestId("rotation")).toHaveTextContent("90");
    const confirm = screen.getByRole("button", {
      name: "Bekräfta maskningen och nästa",
    });
    // The turn is saved first; the button waits for it.
    await waitFor(() => expect(confirm).toBeEnabled());
    fireEvent.click(confirm);
    // Turned a quarter clockwise with the view: the frame round the top two
    // thirds now holds the right two thirds, and the box turns with it.
    expect(actions.confirmMask).toHaveBeenCalledWith(
      12,
      31,
      90,
      0,
      [{ x: 0.45, y: 0.35, w: 0.1, h: 0.3 }],
      { x: expect.closeTo(0.3333, 4), y: 0, w: 0.6667, h: 1 },
      false,
      false,
    );
  });

  it("lays the frame first on the photo, never as the selected box, and hides 'nothing to hide' while it is there", () => {
    const handwritten = doc({
      cert_format: "handskrivet",
      frame_suggestion: UPPER_TWO_THIRDS,
    });
    render(view(item({ documents: [handwritten] })));
    const nothing = () =>
      screen.queryByLabelText("Fotot visar inga säljar- eller köparuppgifter");
    const confirm = screen.getByRole("button", {
      name: "Bekräfta maskningen och nästa",
    });
    const removeBox = screen.getByRole("button", { name: "Ta bort vald ruta" });
    expect(nothing()).toBeNull();
    expect(confirm).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "Lägg till ruta" }));
    expect(screen.getByRole("button", { name: "Ruta 1" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Ramen" }));
    expect(removeBox).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Ruta 1" }));
    fireEvent.click(removeBox);
    expect(screen.queryByRole("button", { name: "Ruta 1" })).toBeNull();
    fireEvent.keyDown(screen.getByRole("button", { name: "Ramen" }), {
      key: "Delete",
    });
    expect(screen.queryByRole("button", { name: "Ramen" })).toBeNull();
    expect(nothing()).toBeInTheDocument();
    expect(confirm).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Lägg till ram" }));
    expect(nothing()).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ta bort ramen" }));
    expect(nothing()).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Lägg till ram" }));
    fireEvent.click(confirm);
    expect(actions.confirmMask).toHaveBeenCalledWith(
      12,
      31,
      0,
      0,
      [],
      UPPER_TWO_THIRDS,
      false,
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
    expect(actions.confirmMask).toHaveBeenCalledWith(
      12,
      31,
      0,
      0,
      [],
      null,
      true,
      false,
    );
  });

  it("lets a manager redo the masking of a finished document, from its stored rotation and frame", () => {
    const done = doc({
      status: "klar",
      has_copy: true,
      rotation: 90,
      mask_rects: [{ x: 0.1, y: 0.1, w: 0.2, h: 0.2 }],
      copy_frame: { x: 0, y: 0, w: 1, h: 0.5 },
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
      0,
      [{ x: 0.1, y: 0.1, w: 0.2, h: 0.2 }],
      { x: 0, y: 0, w: 1, h: 0.5 },
      false,
      false,
    );
  });

  it("records the registry check only when the handler ticks it; the reading only proposes it", () => {
    const box = () =>
      screen.getByLabelText(
        "Jag har jämfört intyget med registret och de stämmer",
      );
    const confirm = () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Bekräfta maskningen och nästa" }),
      );
    const read = (
      fields: NonNullable<InboxDocument["proposal"]>["fields"],
      checks: { ok: boolean | null; text: string }[] = [
        { ok: true, text: "Föräldrarna på intyget stämmer med registret." },
      ],
    ) =>
      doc({
        individual: "G9001-2512",
        interpretation_status: "klar",
        proposal: { fields, checks },
        mask_rects: [{ x: 0, y: 0.6667, w: 1, h: 0.3333 }],
      });
    const own = {
      individual: { value: "G9001-2512", source: "läst" as const },
      paper_certificate: { value: "SYN-1", source: "läst" as const },
    };
    const { unmount } = render(view(item({ documents: [read(own)] })));
    expect(box()).not.toBeChecked();
    expect(screen.getByText(/Förslag: stämmer/)).toBeInTheDocument();
    fireEvent.click(box());
    confirm();
    expect(actions.confirmMask).toHaveBeenLastCalledWith(
      12,
      31,
      0,
      0,
      expect.any(Array),
      null,
      false,
      true,
    );
    unmount();
    // No proposal when the reading names another rabbit, only derives it, or a check failed.
    for (const other of [
      read({ individual: { value: "G9001-2511", source: "läst" } }),
      read({ individual: { value: "G9001-2512", source: "härlett" } }),
      // Read as a rabbit with a digital certificate: no certificate number was compared.
      read({ individual: { value: "G9001-2512", source: "läst" } }),
      read({}, [{ ok: true, text: "Intygsnumret är ledigt." }]),
      read(own, [
        { ok: true, text: "Föräldrarna på intyget stämmer med registret." },
        { ok: false, text: "Namnet skiljer sig." },
      ]),
    ]) {
      const { unmount: done } = render(view(item({ documents: [other] })));
      expect(screen.queryByText(/Förslag: stämmer/)).toBeNull();
      done();
    }
  });

  it("asks for the check again when the masking is redone", () => {
    const done = doc({
      status: "klar",
      has_copy: true,
      verified_at: "2026-11-26T10:00:00+00:00",
    });
    render(
      view(
        item({ state: "klar", assigned_to: other, documents: [done] }),
        boss,
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Gör om maskningen" }));
    expect(
      screen.getByLabelText(
        "Jag har jämfört intyget med registret och de stämmer",
      ),
    ).not.toBeChecked();
  });

  it("offers the redo to a manager of the rabbit's genebank on another genebank's item", () => {
    const done = doc({
      status: "klar",
      has_copy: true,
      individual_genebank_id: 2,
    });
    const mellerud: QueueUser = { id: 4, is_admin: false, is_manager: [2] };
    render(
      view(
        item({ state: "klar", assigned_to: other, documents: [done] }),
        mellerud,
        true,
      ),
    );
    expect(
      screen.getByRole("button", { name: "Gör om maskningen" }),
    ).toBeInTheDocument();
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

describe("WorkView: straightening the photo", () => {
  const paper = { x: 0.1, y: 0.05, w: 0.8, h: 0.9 };

  it("keeps an angle unsaved until the handler saves it, with no part of the photo or new reading meanwhile", async () => {
    render(
      view(
        item({
          documents: [doc({ status: "ny", interpretation_status: "klar" })],
        }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Bifoga utsnitt" }));
    expect(screen.getByText("Utsnittet är ritat")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Räta" }));
    expect(screen.getByTestId("straighten")).toHaveTextContent("4");
    // The part framed at the old angle is gone, and none is framed until the angle is saved.
    expect(screen.queryByText("Utsnittet är ritat")).toBeNull();
    expect(screen.queryByRole("button", { name: "Bifoga utsnitt" })).toBeNull();
    expect(screen.getByRole("button", { name: "Tolka igen" })).toBeDisabled();
    expect(screen.getByText(/Vinkeln 4,0° är inte sparad/)).toBeInTheDocument();
    expect(actions.updateDocument).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Spara vinkeln" }));
    expect(actions.updateDocument).toHaveBeenCalledWith(12, 31, {
      straighten: 4,
    });
    expect(
      await screen.findByText(/Vinkeln är sparad\. Klicka Tolka igen/),
    ).toBeInTheDocument();
  });

  it("takes an unsaved angle into the masking, locks it there and sends it with the masking", () => {
    const { rerender } = render(
      view(item({ documents: [doc({ status: "ny" })] })),
    );
    fireEvent.click(screen.getByRole("button", { name: "Räta" }));
    rerender(view(item({ documents: [doc()] }))); // the rabbit is saved: the masking step
    expect(screen.getByTestId("straighten")).toHaveTextContent("4");
    expect(screen.getByRole("button", { name: "Räta" })).toBeDisabled();
    expect(
      screen.getByText(/Vinkeln 4,0° sparas när du bekräftar maskningen/),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Lägg till ruta" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Bekräfta maskningen och nästa" }),
    );
    expect(actions.confirmMask).toHaveBeenCalledWith(
      12,
      31,
      0,
      4,
      [{ x: 0.35, y: 0.45, w: 0.3, h: 0.1 }],
      UPPER_TWO_THIRDS,
      false,
      false,
    );
    rerender(view(item({ assigned_to: other, documents: [doc()] })));
    expect(screen.getByTestId("straighten")).toHaveTextContent("0"); // another handler: the stored angle
  });

  it("'Hitta pappret' in the masking sends the angle and keeps it, and sets the frame round the paper's upper two thirds, in the view's turn", async () => {
    // Even an answer with another angle changes nothing but the frame: the angle is locked in the masking.
    actions.findPaper.mockResolvedValue({
      ok: true,
      data: { angle: 0, paper },
    });
    render(view(item({ documents: [doc({ straighten: 2.5 })] })));
    fireEvent.click(screen.getByRole("button", { name: "Lägg till ruta" }));
    fireEvent.click(screen.getByRole("button", { name: "Vrid" })); // turned for the masking, not yet stored
    fireEvent.click(screen.getByRole("button", { name: "Hitta pappret" }));
    expect(
      await screen.findByText(
        "Ramen ligger runt pappret utom dess nedre tredjedel.",
      ),
    ).toBeInTheDocument();
    expect(actions.findPaper).toHaveBeenCalledWith(12, 31, 2.5);
    expect(screen.getByTestId("straighten")).toHaveTextContent("2.5");
    const confirm = screen.getByRole("button", {
      name: "Bekräfta maskningen och nästa",
    });
    await waitFor(() => expect(confirm).toBeEnabled()); // the saved turn and the search are done
    fireEvent.click(confirm);
    // The paper was found in the stored rotation (0): a quarter turn on, its upper two thirds. The box stays.
    expect(actions.confirmMask).toHaveBeenCalledWith(
      12,
      31,
      90,
      2.5,
      [{ x: 0.45, y: 0.35, w: 0.1, h: 0.3 }],
      {
        x: expect.closeTo(0.05, 4),
        y: expect.closeTo(0.1, 4),
        w: expect.closeTo(0.9, 4),
        h: expect.closeTo(0.8 * 0.6667, 4),
      },
      false,
      false,
    );
  });

  it("sends the part of the photo with the turn it was drawn in", () => {
    render(
      view(
        item({
          documents: [doc({ status: "ny", rotation: 90, straighten: 2.5 })],
        }),
      ),
    );
    expect(screen.getByTestId("turn")).toHaveTextContent("90:2.5");
  });

  describe("a late answer to 'Hitta pappret'", () => {
    let answer: (value: unknown) => void = () => {};
    const late = () =>
      actions.findPaper.mockReturnValue(
        new Promise((resolve) => (answer = resolve)),
      );
    const arrives = (angle: number) =>
      act(async () => answer({ ok: true, data: { angle, paper } }));

    it("is dropped after another document is chosen", async () => {
      late();
      render(
        view(
          item({
            documents: [
              doc({ status: "ny" }),
              doc({ id: 32, status: "ny", straighten: 1.5 }),
            ],
          }),
        ),
      );
      fireEvent.click(screen.getByRole("button", { name: "Hitta pappret" }));
      fireEvent.click(screen.getByRole("button", { name: /^2\. / }));
      await arrives(4);
      expect(screen.getByTestId("straighten")).toHaveTextContent("1.5");
      expect(screen.queryByText(/Fotot lutar/)).toBeNull();
    });

    it("is dropped after a turn, outside the masking and in it", async () => {
      late();
      const { unmount } = render(
        view(item({ documents: [doc({ status: "ny" })] })),
      );
      fireEvent.click(screen.getByRole("button", { name: "Hitta pappret" }));
      fireEvent.click(screen.getByRole("button", { name: "Vrid" }));
      await arrives(4);
      expect(screen.getByTestId("straighten")).toHaveTextContent("0");
      unmount();

      late();
      render(view(item({ documents: [doc()] })));
      fireEvent.click(screen.getByRole("button", { name: "Hitta pappret" }));
      fireEvent.click(screen.getByRole("button", { name: "Vrid" }));
      await arrives(0);
      expect(screen.queryByText(/Ramen ligger runt pappret/)).toBeNull();
      const confirm = screen.getByRole("button", {
        name: "Bekräfta maskningen och nästa",
      });
      await waitFor(() => expect(confirm).toBeEnabled());
      fireEvent.click(confirm);
      // The frame the step started with, turned with the view: not the paper's.
      expect(actions.confirmMask).toHaveBeenCalledWith(
        12,
        31,
        90,
        0,
        [],
        { x: expect.closeTo(0.3333, 4), y: 0, w: 0.6667, h: 1 },
        false,
        false,
      );
    });
  });

  it("'Hitta pappret' without a clear tilt sets 0°, and is only the handler's", async () => {
    actions.findPaper.mockResolvedValue({
      ok: true,
      data: { angle: 0, paper: null },
    });
    const { unmount } = render(
      view(item({ documents: [doc({ status: "ny", straighten: 3 })] })),
    );
    expect(screen.getByTestId("straighten")).toHaveTextContent("3");
    fireEvent.click(screen.getByRole("button", { name: "Hitta pappret" }));
    expect(
      await screen.findByText(
        "Ingen tydlig lutning hittades, så vinkeln är 0°.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("straighten")).toHaveTextContent("0");
    expect(actions.findPaper).toHaveBeenCalledWith(12, 31); // outside the masking the tilt is looked for
    unmount();
    render(view(item({ assigned_to: other, documents: [doc()] }), boss));
    expect(screen.queryByRole("button", { name: "Hitta pappret" })).toBeNull();
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
    render(view(item({ documents: [form] }), helper, false, [2026]));
    expect(
      screen.getByRole("link", { name: "Mata in årsrapporten" }),
    ).toHaveAttribute("href", "/stamboken/arsrapport/G9001/2026?post=12");
  });

  it("gives a link per year when the form may be for either (#264)", () => {
    render(view(item({ documents: [form] }), helper, false, [2026, 2027]));
    expect(screen.getByText(/Välj året som står på blanketten/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Mata in årsrapporten 2026" }),
    ).toHaveAttribute("href", "/stamboken/arsrapport/G9001/2026?post=12");
    expect(
      screen.getByRole("link", { name: "Mata in årsrapporten 2027" }),
    ).toHaveAttribute("href", "/stamboken/arsrapport/G9001/2027?post=12");
  });

  it("leaves the link out without a round, and for someone who cannot save", () => {
    render(view(item({ documents: [form] })));
    expect(
      screen.queryByRole("link", { name: "Mata in årsrapporten" }),
    ).toBeNull();
    cleanup();
    render(view(item({ documents: [form] }), helper, true, [2026]));
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
    // the field names at reading size, a differing row marked, numbers kept whole (14)
    expect(
      screen.getByRole("table", { name: "Tolkningen och registreringen" })
        .className,
    ).toContain("photoCheck");
    for (const cellText of within(row("Mor")).getAllByText("G9001-24001"))
      expect(cellText.className).toContain("number");
    expect(within(row("Namn")).getByText("Kulla").className).not.toContain(
      "number",
    );
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

  it("lets the handler straighten it, and reads it again only once the angle is saved: it has no masking", () => {
    render(view(photoItem()));
    const straighten = screen.getByRole("button", { name: "Räta" });
    expect(straighten).toBeEnabled();
    fireEvent.click(straighten);
    expect(screen.getByRole("button", { name: "Tolka igen" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Spara vinkeln" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/bekräftar maskningen/)).toBeNull();
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
    render(view(proposal, boss, false, [2026])); // 2026 is the newest round the genebank activated
    expect(screen.getByText(/Avgörs i årsrapportens statusvy/)).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "Öppna statusvyn" }),
    ).toHaveAttribute(
      "href",
      "/stamboken/arsrapport/status/2025?genebank_id=1",
    );
  });

  it("keeps the text without a year", () => {
    render(view({ ...proposal, report_year: null }, boss, false, [2026]));
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
    render(view(sent, boss, false, [2026]));
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

  it("shows its fields in the main column, and opens the rabbit's sale filled in", () => {
    render(view(notice, boss, false, [2026]));
    const main = screen.getByRole("region", { name: "Fotot" });
    const facts = within(main)
      .getAllByRole("term")
      .map((dt) => `${dt.textContent}: ${dt.nextElementSibling?.textContent}`);
    expect(facts).toEqual([
      "Kanin: G9002-2501",
      "Säljare: G9002",
      "Köpare: G9001",
      "Datum: 14 maj 2025",
    ]);
    expect(within(main).queryByText("Ärendet har inga dokument.")).toBeNull();
    expect(
      within(main).getByRole("link", { name: "Registrera försäljningen" }),
    ).toHaveAttribute(
      "href",
      "/stamboken/individ/G9002-2501?salj=1&till=G9001&datum=2025-05-14",
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
    render(view({ ...notice, events: [event] }, boss, false, [2026]));
    expect(screen.getByText(/Inkommet via länk G9001\/2025/)).toBeTruthy();
    // and as its sender: a notice has no sender account
    const sender = screen.getByText("Inskickat av").nextElementSibling;
    expect(sender?.textContent).toBe("länk G9001/2025");
    cleanup();
    const byAccount = {
      ...event,
      user: { id: 9, name: "Ägare Ett" },
      detail: {},
    };
    render(view({ ...notice, events: [byAccount] }, boss, false, [2026]));
    expect(
      screen.getByText("Inskickat av").nextElementSibling?.textContent,
    ).toBe("Ägare Ett");
  });

  it("names the personal link by its herd for a photo that has no sender account", () => {
    render(
      view(
        { ...notice, ref_type: "individual", herd: "M9202", sender: null },
        boss,
        false,
        [2026],
      ),
    );
    expect(
      screen.getByText("Inskickat av").nextElementSibling?.textContent,
    ).toBe("Länken för besättning M9202");
  });

  it("shows a photo sent with it, and nothing to work on from it in the queue", () => {
    render(
      view(
        { ...notice, documents: [doc({ doc_type: "bevis", status: "ny" })] },
        boss,
        false,
        [2026],
      ),
    );
    expect(screen.getByRole("heading", { name: "Anmält köp" })).toBeTruthy();
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
    render(view({ ...taken, documents: [photo] }, helper, false, [2026]));
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
    render(view({ ...notice, report_year: 2025 }, boss, false, [2026]));
    expect(
      screen.getByRole("link", { name: "Öppna statusvyn" }),
    ).toHaveAttribute(
      "href",
      "/stamboken/arsrapport/status/2025?genebank_id=1",
    );
  });
});
