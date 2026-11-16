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

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), replace }),
}));
const readMode = vi.fn(() => "demo" as const);
vi.mock("@/lib/mode", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/mode")>()),
  readModeCookieClient: () => readMode(),
}));

import {
  ReportForm,
  type ReportActions,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/ReportForm";
import type { Receipt } from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";
import { view } from "./fixtures";

// The page behind the personal link (/rapport): the same form in link mode.
const receipt: Receipt = {
  submission_id: 1,
  report_id: 1,
  created_at: "2027-01-03T13:32:00+00:00",
  source: "link",
  summary: { kvar: 2, doda: 0, salda: 0, ej_angivna: 0 },
  matrikel: [],
  warnings: [],
};
const ok = <T,>(data: T) => Promise.resolve({ ok: true as const, data });
const fail = (status: number, extensions: Record<string, unknown> = {}) =>
  Promise.resolve({
    ok: false as const,
    problem: { status, title: "t", detail: "x", extensions },
  });
const actions = (over: Partial<Record<keyof ReportActions, unknown>> = {}) =>
  ({
    saveDraft: vi.fn(() =>
      ok({ updated_at: "2026-12-31T10:00:00+00:00", submission_key: null }),
    ),
    dryRun: vi.fn(() => ok({ ok: true, refusals: [], warnings: [] })),
    submitReport: vi.fn(() => ok(receipt)),
    withdrawReport: vi.fn(),
    getGenebankHerds: vi.fn(),
    ...over,
  }) as never as {
    [K in keyof ReportActions]: ReturnType<typeof vi.fn>;
  } & ReportActions;
const linkForm = (a: ReportActions) => (
  <ReportForm
    link
    env="prod"
    view={view({ access: "code", source: "link" })}
    actions={a}
    stickyTop={0}
  />
);
const row = (n: number) =>
  screen.getByRole("group", { name: new RegExp(`G9001-${n}\\b`) });
const choose = (n: number, label: string) =>
  fireEvent.click(within(row(n)).getByLabelText(label));
const fillAll = () => {
  for (const n of [1, 2]) {
    choose(n, "Finns kvar");
    fireEvent.change(within(row(n)).getByLabelText("Vikt"), {
      target: { value: "2,8" },
    });
  }
};

beforeEach(() => {
  window.scrollTo = vi.fn();
  window.localStorage.clear();
  replace.mockReset();
  readMode.mockClear();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("ReportForm in link mode", () => {
  it("link mode never reads sb_mode", async () => {
    vi.useFakeTimers();
    const a = actions();
    render(linkForm(a));
    fillAll();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100); // the autosave
    });
    expect(a.saveDraft).toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("radio", { name: "Inga sjukdomsfall eller defekter" }),
    );
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Skicka årsrapporten" }),
      );
    });
    expect(a.submitReport).toHaveBeenCalled();
    expect(readMode).not.toHaveBeenCalled();
  });

  it("link mode uses its own storage key", () => {
    render(linkForm(actions()));
    choose(1, "Finns kvar");
    expect(Object.keys(window.localStorage)).toEqual([
      "arsrapport:link:G9001:2026",
    ]);
  });

  it("link mode shows no profile link", () => {
    const { container } = render(linkForm(actions()));
    expect(screen.queryByText("Gå till profilen")).toBeNull();
    expect(container.querySelector('a[href^="/stamboken"]')).toBeNull();
    expect(
      screen.getByText(
        "Har din adress, e-post, ditt konto för stödet eller ditt svar om Koharen ändrats? Kontakta genbanksansvarig.",
      ),
    ).toBeTruthy();
  });

  it("goes to the page for a link that no longer works", async () => {
    const a = actions({
      dryRun: vi.fn(() => fail(403, { code: "lank_ogiltig" })),
    });
    render(linkForm(a));
    fillAll();
    fireEvent.click(
      screen.getByRole("radio", { name: "Inga sjukdomsfall eller defekter" }),
    );
    await act(async () => {
      fireEvent.click(
        screen.getByRole("button", { name: "Skicka årsrapporten" }),
      );
    });
    expect(replace).toHaveBeenCalledWith("/rapport/ogiltig");
  });

  it("says the page was closed, not that the user was signed out, on 401", async () => {
    vi.useFakeTimers();
    const a = actions({
      saveDraft: vi.fn(() => fail(401, { code: "session_ute" })),
    });
    render(linkForm(a));
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(
      screen.queryAllByText(/Sidan stängdes efter två timmar/).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByText(/Logga in igen/)).toBeNull();
  });
});
