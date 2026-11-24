import "@testing-library/jest-dom/vitest";
import "@/i18n";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";

const { fetchApi, replace, push } = vi.hoisted(() => ({
  fetchApi: vi.fn(),
  replace: vi.fn(),
  push: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace, push }) }));
vi.mock("@/lib/api", async (original) => ({
  ...(await original<typeof import("@/lib/api")>()),
  fetchApi,
}));
vi.mock("@/lib/auth", () => ({
  requireUser: async () => ({ id: 3, fullname: "Konto 3", is_manager: [1] }),
}));
vi.mock("@/lib/inkorg-server", () => ({
  requireQueueWorker: async () => undefined,
  fetchHandlers: async () => [],
  getInboxCount: async () => ({ unread: 0 }),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/GmailAlarm", () => ({
  GmailAlarm: () => null,
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/QueueControls", () => ({
  AssignHerd: () => null,
}));

vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/ItemControls", () => ({
  ItemControls: () => null,
}));

import InkorgPage from "@/app/(app)/stamboken/(dashboard)/inkorg/page";

const row = {
  id: 14,
  subject: "Intyg för kullen",
  kind: "mail",
  herd: "G12",
  state: "ny",
  sender_address: "avsandare@example.org",
  documents: 2,
  received_at: "2020-01-01T12:00:00Z",
  assigned_to: null,
  maybe_blurry: true,
  has_skipped: true,
};
const queue = {
  items: [
    row,
    { ...row, id: 15, subject: "En följdfråga", member_name: "Medlem A" },
  ],
  total: 2,
  next_untaken: [14, 15],
  mode_counts: { nya: 2, mina: 5, oppna: 8, klara: 40 },
  scope: "mina",
  my_genebanks: [1],
};
let wideScreen = false;
beforeEach(() => {
  wideScreen = false;
  vi.clearAllMocks();
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches: wideScreen,
      addEventListener() {},
      removeEventListener() {},
    })),
  );
  fetchApi.mockResolvedValue(queue);
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const show = async (sp: Record<string, string> = {}) =>
  render(await InkorgPage({ searchParams: Promise.resolve(sp) }));

describe("Inkorg", () => {
  it("shows the base API's list, scope and detail with only supported controls", async () => {
    const received = "2020-01-01T12:00:00+00:00";
    const item = {
      id: 14,
      kind: "mail",
      state: "ny",
      genebank_id: 1,
      herd: "G12",
      received_at: received,
      state_changed_at: received,
      closed_at: null,
      sender: null,
      assigned_to: null,
      assigned_at: null,
      duplicate_of: null,
      stalled: false,
      missing_proof: false,
      ref_type: null,
      ref_id: null,
      sender_authenticated: true,
      has_message: true,
      maybe_blurry: false,
      documents: 0,
      documents_done: 0,
    };
    fetchApi.mockImplementation(async (path: string) =>
      path === "/v2/inkorg/14"
        ? {
            ...item,
            events: [],
            documents: [],
            sender_address: "test@example.org",
          }
        : {
            items: [item],
            total: 1,
            counts: { ny: 1 },
            scope: "mina",
            my_genebanks: [1],
            interpretation: {
              interpreter: "av",
              waiting: 0,
              last_done_at: null,
              alarm: false,
            },
          },
    );
    await show({ arende: "14" });
    expect(screen.getByRole("link", { name: /#14 Mejl/ })).toBeVisible();
    expect(screen.getByRole("link", { name: "Mina genbanker" })).toBeVisible();
    expect(screen.queryByRole("link", { name: /^Klara/ })).toBeNull();
    expect(screen.getByRole("searchbox")).toBeDisabled();
    expect(screen.getByRole("combobox", { name: "Ordning" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Nästa ärende" })).toBeDisabled();
  });

  it("shows the scoped totals, initial scope and oldest-first ordering", async () => {
    await show();
    expect(fetchApi.mock.calls[0][0]).not.toContain("scope=");
    expect(
      screen.getByRole("link", { name: "Mina genbanker" }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Alla" })).toHaveAttribute(
      "href",
      "/stamboken/inkorg?scope=alla",
    );
    expect(screen.getByRole("link", { name: "Mina 5" })).toBeVisible();
    expect(screen.getByRole("link", { name: "Klara 40" })).toBeVisible();
    expect(screen.getByRole("combobox", { name: "Ordning" })).toHaveValue(
      "oldest",
    );
    expect(replace).not.toHaveBeenCalled();
  });

  it("links by subject, includes sender, flags and exactly one state label", async () => {
    await show();
    const item = screen.getByRole("link", { name: /#14 Intyg för kullen/ });
    expect(item).toHaveAttribute("href", "/stamboken/inkorg?arende=14");
    expect(item).toHaveTextContent(
      "okänd avsändare · G12 · mejl · 2 foton · Ingen har tagit det",
    );
    expect(screen.queryByText(/avsandare@example.org/)).toBeNull();
    expect(screen.getByRole("link", { name: /#15/ })).toHaveTextContent(
      "Medlem A",
    );
    expect(within(item).getByText("Ny")).toBeVisible();
    for (const flag of [
      "kan vara oskarp",
      "bilden sparades inte",
      "har väntat länge",
    ])
      expect(within(item).getByText(flag)).toBeVisible();
  });

  it("moves focus without opening either adjacent item on a wide screen", async () => {
    wideScreen = true;
    await show({ scope: "alla" });
    const first = screen.getByRole("link", { name: /#14/ });
    const second = screen.getByRole("link", { name: /#15/ });
    expect(first.tabIndex).toBe(0);
    expect(second.tabIndex).toBe(-1);
    first.focus();
    fireEvent.keyDown(first, { key: "ArrowDown" });
    expect(second).toHaveFocus();
    fireEvent.keyDown(second, { key: "ArrowUp" });
    expect(first).toHaveFocus();
    expect(replace).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
    expect(fetchApi).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/Upp- och nedpil.*Enter/)).toBeVisible();
  });

  it("keeps the narrow list open through two arrow presses", async () => {
    fetchApi.mockResolvedValue({
      ...queue,
      items: [...queue.items, { ...row, id: 16 }],
      total: 3,
    });
    await show();
    screen.getByRole("link", { name: /#14/ }).focus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(screen.getByRole("link", { name: /#15/ })).toHaveFocus();
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    const third = screen.getByRole("link", { name: /#16/ });
    expect(third).toHaveFocus();
    expect(third).toHaveAttribute("href", "/stamboken/inkorg?arende=16");
    expect(replace).not.toHaveBeenCalled();
    expect(push).not.toHaveBeenCalled();
  });

  it("waits for an explicit selection on a wide screen", async () => {
    wideScreen = true;
    await show();
    expect(screen.getByText("Välj ett ärende i listan.")).toBeVisible();
    expect(replace).not.toHaveBeenCalled();
    expect(fetchApi).toHaveBeenCalledTimes(1);
    expect(document.querySelector("img")).toBeNull();
  });

  it("resets an empty filtered list and keeps its scope", async () => {
    fetchApi.mockResolvedValue({ ...queue, items: [], total: 0 });
    await show({ mode: "mina", scope: "alla", herd: "M44", order: "newest" });
    const query = new URL(fetchApi.mock.calls[0][0], "https://example.org")
      .searchParams;
    expect(Object.fromEntries(query)).toMatchObject({
      mode: "mina",
      scope: "alla",
      herd_prefix: "M44",
      order: "newest",
    });
    expect(screen.getByText("Inga ärenden här.")).toBeVisible();
    const reset = screen.getByRole("link", { name: "Visa alla öppna" });
    expect(reset.getAttribute("href")).toContain("scope=alla");
    expect(reset.getAttribute("href")).not.toMatch(/herd|mode=mina/);
  });

  it("loads a bookmarked case even outside the current page, and finds the next free case in scope", async () => {
    fetchApi.mockImplementation(async (path: string) =>
      path === "/v2/inkorg/17"
        ? {
            ...row,
            id: 17,
            documents: [],
            events: [],
            subject: "Mejlet i länken",
          }
        : { ...queue, next_untaken: [17, 25] },
    );
    await show({
      arende: "17",
      scope: "alla",
      mode: "mina",
      herd: "G12",
      offset: "50",
    });
    expect(
      screen.getByRole("heading", { name: "#17 Mejlet i länken" }),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: "Nästa ärende" })).toHaveAttribute(
      "href",
      "/stamboken/inkorg?scope=alla&mode=nya&arende=25",
    );
    expect(
      screen
        .getByRole("link", { name: "Tillbaka till listan" })
        .getAttribute("href"),
    ).toContain("offset=50");
  });

  it.each([
    ["Mina 5", "mode", "mina"],
    ["Alla", "scope", "alla"],
  ])(
    "carries the pending herd search when switching to %s",
    async (name, key, value) => {
      vi.useFakeTimers();
      await show({ offset: "50", herd: "M44" });
      const input = screen.getByRole("searchbox");
      fireEvent.change(input, { target: { value: " g12 " } });
      vi.advanceTimersByTime(200);
      const link = screen.getByRole("link", { name });
      const destination = new URL(
        link.getAttribute("href")!,
        "https://example.org",
      );
      expect(Object.fromEntries(destination.searchParams)).toEqual({
        herd: "G12",
        [key]: value,
      });
      link.addEventListener("click", (event) => event.preventDefault(), {
        once: true,
      });
      fireEvent.click(link);
      vi.advanceTimersByTime(250);
      expect(replace).not.toHaveBeenCalled();
    },
  );

  it("keeps a newer search pending when the previous results arrive", async () => {
    vi.useFakeTimers();
    const view = await show();
    const input = screen.getByRole("searchbox");
    input.focus();
    fireEvent.change(input, { target: { value: "G" } });
    vi.advanceTimersByTime(250);
    fireEvent.change(input, { target: { value: "G12" } });
    view.rerender(
      await InkorgPage({ searchParams: Promise.resolve({ herd: "G" }) }),
    );
    vi.advanceTimersByTime(250);
    expect(replace).toHaveBeenLastCalledWith("/stamboken/inkorg?herd=G12", {
      scroll: false,
    });
  });

  it("updates the herd search and clears the page offset", async () => {
    vi.useFakeTimers();
    await show({ offset: "50" });
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "g12" },
    });
    vi.advanceTimersByTime(350);
    expect(replace).toHaveBeenLastCalledWith("/stamboken/inkorg?herd=G12", {
      scroll: false,
    });
  });
});
