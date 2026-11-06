// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

const { linkPersonUserMock, showSnackbarMock, addNotificationMock } =
  vi.hoisted(() => ({
    linkPersonUserMock: vi.fn(),
    showSnackbarMock: vi.fn(),
    addNotificationMock: vi.fn(),
  }));

vi.mock("@/app/(app)/medlem/matrikel/actions", () => ({
  linkPersonUser: linkPersonUserMock,
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: showSnackbarMock }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification: addNotificationMock }),
}));

import { KopplaKontoDialog } from "@/app/(app)/medlem/matrikel/[id]/KopplaKontoDialog";
import type { Person } from "@/app/(app)/medlem/matrikel/types";

const PERSON: Person = {
  id: 2,
  first_name: "Erik",
  last_name: "Lindqvist",
  email: "erik@example.com",
  phone: null,
  role: "familjemedlem",
  end_date: null,
  user_id: null,
  user: null,
  grants: [],
};

const HIT = {
  id: 42,
  username: "erik.lindqvist",
  email: "erik.lindqvist@example.com",
};

const CONVEYS = [{ id: 3, herd: "G1274", herd_name: "Solhaga" }];

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  vi.useFakeTimers();
  linkPersonUserMock.mockReset();
  showSnackbarMock.mockReset();
  addNotificationMock.mockReset();
  fetchMock = vi.fn(async () => ({
    ok: true,
    json: async () => ({ users: [HIT] }),
  }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** Render the open dialog and type `er` past the 300 ms debounce. */
async function searchFor(onClose = vi.fn()) {
  render(
    <KopplaKontoDialog
      open
      person={PERSON}
      membershipId={1}
      membershipNumber={1274}
      onClose={onClose}
    />,
  );
  fireEvent.change(screen.getByLabelText("Sök användare"), {
    target: { value: "er" },
  });
  await act(async () => {
    vi.advanceTimersByTime(300);
  });
  return onClose;
}

/** Click "Koppla konto" and let the transition settle. */
async function clickKoppla() {
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Koppla konto" }));
  });
}

describe("KopplaKontoDialog", () => {
  it("searches after the debounce and lists username + e-post", async () => {
    await searchFor();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/v2/users/search?q=er");
    expect(screen.getByText("erik.lindqvist")).toBeInTheDocument();
    expect(screen.getByText("erik.lindqvist@example.com")).toBeInTheDocument();
  });

  it("drops a search response that arrives after the query moved on", async () => {
    // The effect aborts an in-flight request only once the
    // DEBOUNCED value changes — a slow response for "er" could otherwise land
    // after the admin typed on, and its hits be selected and linked.
    type Resp = { ok: boolean; json: () => Promise<unknown> };
    let resolveFirst!: (v: Resp) => void;
    const first = new Promise<Resp>((r) => {
      resolveFirst = r;
    });
    fetchMock
      .mockImplementationOnce(() => first)
      .mockImplementationOnce(async () => ({
        ok: true,
        json: async () => ({
          users: [{ id: 7, username: "erika", email: "erika@example.com" }],
        }),
      }));
    await searchFor(); // "er" — first request stays in flight
    fireEvent.change(screen.getByLabelText("Sök användare"), {
      target: { value: "erika" },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.getByText("erika")).toBeInTheDocument();
    await act(async () => {
      resolveFirst({ ok: true, json: async () => ({ users: [HIT] }) });
    });
    expect(screen.queryByText("erik.lindqvist")).not.toBeInTheDocument();
    expect(screen.getByText("erika")).toBeInTheDocument();
  });

  it("ignores a search response that arrives after the dialog closed", async () => {
    type Resp = { ok: boolean; json: () => Promise<unknown> };
    let resolveFirst!: (v: Resp) => void;
    fetchMock.mockImplementationOnce(
      () =>
        new Promise<Resp>((r) => {
          resolveFirst = r;
        }),
    );
    const onClose = await searchFor(); // request in flight
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(onClose).toHaveBeenCalled();
    await act(async () => {
      resolveFirst({ ok: true, json: async () => ({ users: [HIT] }) });
    });
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
  });

  it("does not re-run the old query on a close → immediate reopen", async () => {
    // Avbryt resets `q` but the debounced value keeps the old
    // query for 300 ms; reopening within that window must not fetch it again
    // and list its hits under an empty field.
    const onClose = vi.fn();
    const dialog = (open: boolean) => (
      <KopplaKontoDialog
        open={open}
        person={PERSON}
        membershipId={1}
        membershipNumber={1274}
        onClose={onClose}
      />
    );
    const view = render(dialog(true));
    fireEvent.change(screen.getByLabelText("Sök användare"), {
      target: { value: "er" },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(onClose).toHaveBeenCalled();
    view.rerender(dialog(false));
    view.rerender(dialog(true)); // reopened inside the debounce window
    await act(async () => {
      vi.advanceTimersByTime(50);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("option")).not.toBeInTheDocument();
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(
      (screen.getByLabelText("Sök användare") as HTMLInputElement).value,
    ).toBe("");
  });

  it("does not search below two characters", async () => {
    render(
      <KopplaKontoDialog
        open
        person={PERSON}
        membershipId={1}
        membershipNumber={1274}
        onClose={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Sök användare"), {
      target: { value: "e" },
    });
    await act(async () => {
      vi.advanceTimersByTime(300);
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("enables Koppla konto only once a hit is selected", async () => {
    await searchFor();

    expect(screen.getByRole("button", { name: "Koppla konto" })).toBeDisabled();
    fireEvent.click(screen.getByRole("option", { name: /erik\.lindqvist/ }));
    expect(screen.getByRole("button", { name: "Koppla konto" })).toBeEnabled();
  });

  it("selects a hit from the keyboard", async () => {
    await searchFor();

    const option = screen.getByRole("option", { name: /erik\.lindqvist/ });
    expect(option).toHaveAttribute("tabindex", "0");
    fireEvent.keyDown(option, { key: "Enter" });
    expect(screen.getByRole("button", { name: "Koppla konto" })).toBeEnabled();
    expect(option).toHaveAttribute("aria-selected", "true");
  });

  it("wires the search field to the listbox as a combobox", async () => {
    await searchFor();

    const input = screen.getByLabelText("Sök användare");
    expect(input).toHaveAttribute("role", "combobox");
    expect(input).toHaveAttribute("aria-expanded", "true");
    expect(input).toHaveAttribute("aria-controls", "koppla-hits");
    expect(screen.getByRole("listbox")).toHaveAttribute("id", "koppla-hits");
  });

  it("treats a confirm-required with no herds as an error, not a banner", async () => {
    await searchFor();
    fireEvent.click(screen.getByRole("option", { name: /erik\.lindqvist/ }));

    linkPersonUserMock.mockResolvedValueOnce({
      ok: false,
      confirmRequired: { conveysHerds: [] },
    });
    await clickKoppla();

    expect(showSnackbarMock).toHaveBeenCalledWith(
      "Kunde inte koppla kontot — ladda om sidan",
      "error",
    );
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("warns on the first click and confirms the exact herd ids on the second", async () => {
    const onClose = await searchFor();
    fireEvent.click(screen.getByRole("option", { name: /erik\.lindqvist/ }));

    linkPersonUserMock.mockResolvedValueOnce({
      ok: false,
      confirmRequired: { conveysHerds: CONVEYS },
    });
    await clickKoppla();

    expect(linkPersonUserMock).toHaveBeenCalledWith(1, 2, 42, undefined);
    expect(screen.getByRole("status")).toHaveTextContent(
      "Kontot får ägaråtkomst till G1274 — Solhaga. erik.lindqvist har i dag " +
        "ingen egen ägarbehörighet på besättningen. Kopplingen loggas i matrikelloggen.",
    );
    expect(showSnackbarMock).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();

    linkPersonUserMock.mockResolvedValueOnce({ ok: true });
    await clickKoppla();

    expect(linkPersonUserMock).toHaveBeenLastCalledWith(1, 2, 42, [3]);
    expect(showSnackbarMock).toHaveBeenCalledWith("Konto kopplat", "success");
    expect(onClose).toHaveBeenCalled();
  });
});
