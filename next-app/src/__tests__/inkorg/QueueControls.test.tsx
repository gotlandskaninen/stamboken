import "@/i18n";
import "@testing-library/jest-dom/vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const actions = vi.hoisted(() => ({
  previewHerd: vi.fn(),
  assignHerd: vi.fn(),
  takeItem: vi.fn(),
  releaseItem: vi.fn(),
  undoAssignment: vi.fn(),
}));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/actions", () => actions);

import { ItemControls } from "@/app/(app)/stamboken/(dashboard)/inkorg/ItemControls";
import { AssignHerd } from "@/app/(app)/stamboken/(dashboard)/inkorg/QueueControls";
import {
  QueueUndoProvider,
  QueueUndoStatus,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/QueueUndo";
import type {
  ItemState,
  Person,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

const me = { id: 3, name: "Konto 3" };
const other = { id: 7, name: "Handläggare B" };
const user = { ...me, is_admin: false, is_manager: [1] };
const itemView = (state: ItemState, handler: Person | null) => (
  <QueueUndoProvider>
    <h2 id="case-subject">Ärendet</h2>
    <ItemControls
      item={{
        id: 12,
        genebank_id: 1,
        state,
        assigned_to: handler,
        assigned_at: handler ? "2026-11-14T08:00:00+00:00" : null,
      }}
      user={user}
      myGenebanks={[1]}
    />
  </QueueUndoProvider>
);

async function advance(ms: number) {
  await act(() => vi.advanceTimersByTimeAsync(ms));
}

beforeEach(() => {
  vi.resetAllMocks();
  vi.useFakeTimers();
  actions.undoAssignment.mockResolvedValue({
    ok: true,
    data: { restored: [12] },
  });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("handläggning och ångra", () => {
  it("keeps undo in the layout when a taken item opens in registration", async () => {
    actions.takeItem.mockResolvedValue({ ok: true, data: { undo: "taken" } });
    actions.undoAssignment.mockResolvedValueOnce({
      ok: true,
      data: { restored: [12], warning: "Mejlet kunde inte skickas om." },
    });
    const view = render(itemView("ny", null));
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Börja registrera" }));
    });
    expect(actions.takeItem).toHaveBeenCalledWith(12, undefined);
    expect(push).toHaveBeenCalledWith("/stamboken/inkorg/12");
    expect(screen.getByRole("heading")).toHaveFocus();
    view.rerender(
      <QueueUndoProvider>
        <p>Registrering</p>
        <QueueUndoStatus />
      </QueueUndoProvider>,
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Ångra" }));
    });
    expect(actions.undoAssignment).toHaveBeenCalledWith("taken");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Ändringen har ångrats. Mejlet kunde inte skickas om.",
    );
  });

  it.each([
    [409, "Utskicket pågår. Försök igen."],
    [502, "Det gick inte att nå servern."],
  ])("allows retrying undo after %i", async (status, detail) => {
    actions.takeItem.mockResolvedValue({
      ok: true,
      data: { undo: "same-token" },
    });
    actions.undoAssignment.mockResolvedValueOnce({
      ok: false,
      problem: { status, detail },
    });
    render(itemView("tagen", other));
    await act(async () =>
      fireEvent.click(screen.getByRole("button", { name: /Ta över/ })),
    );
    const undo = () => screen.getByRole("button", { name: "Ångra" });
    await act(async () => fireEvent.click(undo()));
    expect(screen.getByRole("alert")).toHaveTextContent(String(detail));
    await act(async () => fireEvent.click(undo()));
    expect(actions.undoAssignment.mock.calls).toEqual([
      ["same-token"],
      ["same-token"],
    ]);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Ändringen har ångrats.",
    );
  });

  it("announces in an existing status and pauses the timer for hover and focus", async () => {
    actions.takeItem.mockResolvedValue({ ok: true, data: { undo: "over" } });
    render(itemView("tagen", other));
    const status = screen.getByRole("status");
    expect(status).toBeEmptyDOMElement();
    await act(async () =>
      fireEvent.click(screen.getByRole("button", { name: /Ta över/ })),
    );
    expect(screen.getByRole("status")).toBe(status);
    const undo = screen.getByRole("button", { name: "Ångra" });
    fireEvent.mouseEnter(status);
    await advance(20_001);
    expect(undo).toBeVisible();
    act(() => undo.focus());
    fireEvent.mouseLeave(status);
    await advance(20_001);
    expect(undo).toHaveFocus();
    await act(async () => fireEvent.click(undo));
    expect(screen.getByRole("heading", { name: "Ärendet" })).toHaveFocus();
    await advance(20_000);
    expect(status).toBeEmptyDOMElement();
  });

  it("offers undo for takeover and putting a taken case back", async () => {
    actions.takeItem.mockResolvedValue({ ok: true, data: { undo: "over" } });
    actions.releaseItem.mockResolvedValue({
      ok: true,
      data: { undo: "released" },
    });
    const view = render(itemView("tagen", other));
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Ta över från Handläggare" }),
      );
    });
    expect(actions.takeItem).toHaveBeenCalledWith(12, {
      assigned_to: other.id,
      assigned_at: "2026-11-14T08:00:00+00:00",
    });
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByRole("heading")).toHaveFocus();
    await advance(19_999);
    expect(screen.getByRole("button", { name: "Ångra" })).toBeEnabled();
    await advance(1);
    expect(screen.queryByRole("button", { name: "Ångra" })).toBeNull();

    for (const waiting of [
      "vantar_uppfodare",
      "vantar_foralder",
      "ofullstandig",
    ] as const) {
      view.rerender(itemView(waiting, me));
      expect(
        screen.queryByRole("button", { name: "Lägg tillbaka" }),
      ).toBeNull();
    }
    view.rerender(itemView("tagen", me));
    expect(
      screen.getByRole("link", { name: "Börja registrera" }),
    ).toHaveAttribute("href", "/stamboken/inkorg/12");
    await act(async () => {
      const putBack = screen.getByRole("button", { name: "Lägg tillbaka" });
      putBack.focus();
      fireEvent.click(putBack);
    });
    expect(actions.releaseItem).toHaveBeenCalledWith(12);
    expect(screen.getByRole("heading")).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Du lade tillbaka ärende 12.",
    );
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Ångra" }));
    });
    expect(actions.undoAssignment).toHaveBeenCalledWith("released");
  });
});

describe("tilldelning av en besättning", () => {
  function openForm() {
    render(
      <QueueUndoProvider>
        <AssignHerd people={[me, other]} />
      </QueueUndoProvider>,
    );
    fireEvent.click(screen.getByText("Ge en hel besättning till en person"));
    fireEvent.change(screen.getByLabelText("Besättning"), {
      target: { value: " g9001 " },
    });
    fireEvent.change(screen.getByLabelText("Till"), { target: { value: "3" } });
  }

  it("shows who already handles items and assigns the exact preview with one undo", async () => {
    actions.previewHerd.mockResolvedValue({
      ok: true,
      data: {
        total: 4,
        revision: "preview",
        assignees: [
          { ...other, count: 2 },
          { ...me, count: 1 },
        ],
      },
    });
    actions.assignHerd.mockResolvedValue({
      ok: true,
      data: { assigned: [12, 13, 14, 15], undo: "batch" },
    });
    openForm();
    expect(screen.getByRole("button", { name: "Tilldela" })).toBeDisabled();
    await advance(260);
    expect(actions.previewHerd).toHaveBeenCalledWith("G9001");
    expect(
      screen.getByText("4 öppna ärenden i G9001").parentElement,
    ).toHaveTextContent(
      "4 öppna ärenden i G9001, varav 2 redan ligger hos Handläggare B.",
    );
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Tilldela 4 ärenden" }),
      );
    });
    expect(actions.assignHerd).toHaveBeenCalledWith("G9001", 3, "preview");
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Ångra" }));
    });
    expect(actions.undoAssignment).toHaveBeenCalledWith("batch");
  });

  it("disables assignment on herd change and reloads a refused preview for review", async () => {
    actions.previewHerd.mockResolvedValue({
      ok: true,
      data: { total: 1, revision: "older", assignees: [] },
    });
    actions.assignHerd.mockResolvedValue({
      ok: false,
      problem: { status: 409, detail: "Ärendena har ändrats." },
    });
    openForm();
    await advance(260);
    fireEvent.change(screen.getByLabelText("Besättning"), {
      target: { value: "G9002" },
    });
    expect(screen.getByRole("button", { name: "Tilldela" })).toBeDisabled();
    await advance(260);
    actions.previewHerd.mockResolvedValue({
      ok: true,
      data: { total: 0, revision: "newer", assignees: [] },
    });
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Tilldela 1 ärende" }),
      );
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Ärendena har ändrats.",
    );
    await advance(260);
    expect(
      screen.getByText("Besättningen har inga öppna ärenden."),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Tilldela" })).toBeDisabled();
  });
});
