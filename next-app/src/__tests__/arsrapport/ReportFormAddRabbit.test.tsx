import "@testing-library/jest-dom/vitest";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

// "Lägg till kanin från intyget" in the report page (4b Task 4): where it is offered, and what a registration does
// to the page. The dialog itself is AddRabbit.test.tsx; here it stands in with what it hands back on closing.
const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
let where = "hos_mig"; // what the stand-in hands back as "var är kaninen nu"
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/arsrapport/AddRabbit",
  async (original) => ({
    ...(await original<object>()),
    AddRabbitDialog: ({
      onClose,
    }: {
      onClose: (registered: unknown[]) => void;
    }) => (
      <button
        type="button"
        onClick={() =>
          onClose([
            [{ id: 2, number: "G9001-2", item_id: 7, listed: true }, where],
          ])
        }
      >
        Registrerad
      </button>
    ),
  }),
);

import { ReportForm } from "@/app/(app)/stamboken/(dashboard)/arsrapport/ReportForm";
import {
  ADD_FROM_CERTIFICATE,
  RABBIT_SAVED,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/AddRabbit";
import { view } from "./fixtures";

const actions = () =>
  ({
    saveDraft: vi.fn(() =>
      Promise.resolve({
        ok: true,
        data: { updated_at: "2026-12-31T10:00:00+00:00", submission_key: null },
      }),
    ),
    dryRun: vi.fn(),
    submitReport: vi.fn(),
    withdrawReport: vi.fn(),
    getGenebankHerds: vi.fn(() =>
      Promise.resolve({ success: true, herds: [] }),
    ), // the sale dialog's herd picker
  }) as never;

// a helper's paper form, as paper.test.tsx sets it up
const PAPER_ITEM = {
  id: 5,
  received_at: "2027-01-03T10:00:00+00:00",
  state: "tagen",
  account_end: "12",
};
const PAPER = {
  documentIds: [11],
  intygPending: false,
  archive: vi.fn() as never,
  leave: vi.fn(),
};

beforeEach(() => {
  window.scrollTo = vi.fn(); // jsdom does not implement it
  window.localStorage.clear();
  refresh.mockReset();
  where = "hos_mig";
});
afterEach(cleanup);

describe("Lägg till kanin från intyget in the report", () => {
  it("is offered under the rabbit list beside Anmäl köpet, and in an empty list too", () => {
    const button = () =>
      screen.getByRole("button", { name: "Lägg till kanin från intyget" });
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    expect(screen.getAllByText(ADD_FROM_CERTIFICATE)).toHaveLength(1);
    const purchase = screen.getByRole("button", { name: "Anmäl köpet" });
    expect(button().closest("div")).toBe(purchase.closest("div"));
    expect(
      within(
        screen
          .getByRole("heading", { name: /^Sålda under/ })
          .closest("section") ?? document.body,
      ).queryByRole("button", { name: "Lägg till kanin från intyget" }),
    ).toBeNull();
    cleanup();
    render(
      <ReportForm
        env="demo"
        view={view({ rabbits: [] })}
        actions={actions()}
      />,
    );
    // the empty list says it once, in its own words, just above the button
    expect(
      screen.getAllByText(
        (_, el) =>
          !!el?.matches("p") && el.textContent!.includes(ADD_FROM_CERTIFICATE),
      ),
    ).toHaveLength(1);
    expect(screen.queryByText(/Kontakta genbanksansvarig/)).toBeNull();
    expect(button()).toBeTruthy();
  });

  it("is not offered on a paper form, which the queue registers from", () => {
    render(
      <ReportForm
        env="demo"
        view={view({ access: "helper", source: "paper", item: PAPER_ITEM })}
        actions={actions()}
        post={5}
        paper={PAPER}
      />,
    );
    expect(screen.queryByText(ADD_FROM_CERTIFICATE)).toBeNull();
  });

  it("reads the page again on Back when a save went out while the list was being read again", async () => {
    vi.useFakeTimers();
    const a = actions() as unknown as { saveDraft: ReturnType<typeof vi.fn> };
    const { rerender, unmount } = render(
      <ReportForm env="demo" view={view()} actions={a as never} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Lägg till kanin från intyget" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Registrerad" })); // the list is asked for again
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100); // the row's new choice is saved meanwhile
    });
    expect(a.saveDraft).toHaveBeenCalled();
    const read = view(); // the list that answers, read before that save
    rerender(<ReportForm env="demo" view={read} actions={a as never} />);
    unmount();
    refresh.mockReset();
    render(<ReportForm env="demo" view={read} actions={a as never} />); // Back
    await act(async () => {});
    expect(refresh).toHaveBeenCalledTimes(1);
    vi.useRealTimers();
  });

  it("after a registration: the list is read again, the note says it stays, and the row takes 'var är kaninen nu'", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Lägg till kanin från intyget" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Registrerad" }));
    expect(refresh).toHaveBeenCalled();
    expect(screen.getByText(RABBIT_SAVED)).toHaveAttribute("role", "status");
    const row = document.getElementById("rabbit-2")!;
    expect(
      within(row).getByRole("radio", { name: "Finns kvar" }),
    ).toBeChecked();
  });

  it("a rabbit registered as sold opens the sale dialog for a link and a caretaker too, whose sale is a proposal", () => {
    where = "sald";
    for (const [link, access] of [
      [true, "code"],
      [false, "caretaker"],
    ] as const) {
      render(
        <ReportForm
          link={link || undefined}
          env="demo"
          view={view({ access, can_sell: false })}
          actions={actions()}
        />,
      );
      fireEvent.click(
        screen.getByRole("button", { name: "Lägg till kanin från intyget" }),
      );
      fireEvent.click(screen.getByRole("button", { name: "Registrerad" }));
      expect(
        screen.getByRole("dialog", { name: "Såld: G9001-2" }),
      ).toBeTruthy();
      cleanup();
    }
  });
});
