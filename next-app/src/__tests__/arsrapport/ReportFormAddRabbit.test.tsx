import "@testing-library/jest-dom/vitest";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
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
            [{ id: 2, number: "G9001-2", item_id: 7, listed: true }, "hos_mig"],
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
    getGenebankHerds: vi.fn(),
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
});
afterEach(cleanup);

describe("Lägg till kanin från intyget in the report", () => {
  it("is offered under Sålda under Y, and in an empty list too", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    expect(screen.getAllByText(ADD_FROM_CERTIFICATE)).toHaveLength(1);
    cleanup();
    render(
      <ReportForm
        env="demo"
        view={view({ rabbits: [] })}
        actions={actions()}
      />,
    );
    expect(screen.getAllByText(ADD_FROM_CERTIFICATE)).toHaveLength(2);
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
});
