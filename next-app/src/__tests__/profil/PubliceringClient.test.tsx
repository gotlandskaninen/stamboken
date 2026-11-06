import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { stambokenTheme } from "@/theme/stamboken";

const { showSnackbar, addNotification } = vi.hoisted(() => ({
  showSnackbar: vi.fn(),
  addNotification: vi.fn(),
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification }),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/profil/actions", () => ({
  updateConsent: vi.fn(),
}));

import { updateConsent } from "@/app/(app)/stamboken/(dashboard)/profil/actions";
import { PubliceringClient } from "@/app/(app)/stamboken/(dashboard)/profil/PubliceringClient";

const initial = { name: true, phone: false, email: false, address: false };
const renderIt = (readOnly = false, answered = true) =>
  render(
    <ThemeProvider theme={stambokenTheme}>
      <PubliceringClient
        readOnly={readOnly}
        initial={initial}
        answered={answered}
      />
    </ThemeProvider>,
  );

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PubliceringClient", () => {
  it("renders the Koharen heading and lead text", () => {
    renderIt();
    expect(screen.getByText("Publicering i Koharen")).toBeDefined();
    expect(screen.getByText(/Inget av detta visas på webben/)).toBeDefined();
  });

  it("reflects the initial consent on the four switches", () => {
    renderIt();
    expect((screen.getByLabelText("Namn") as HTMLInputElement).checked).toBe(
      true,
    );
    expect((screen.getByLabelText("Telefon") as HTMLInputElement).checked).toBe(
      false,
    );
    expect((screen.getByLabelText("E-post") as HTMLInputElement).checked).toBe(
      false,
    );
    expect((screen.getByLabelText("Adress") as HTMLInputElement).checked).toBe(
      false,
    );
  });

  it("saves ONLY the switches that moved and confirms with a snackbar", async () => {
    // Partial update: a second tab editing another switch must not
    // have its value replayed from this tab's stale read.
    vi.mocked(updateConsent).mockResolvedValue({
      ok: true,
      consent: { ...initial, email: true },
      answered: true,
    });
    renderIt();
    fireEvent.click(screen.getByLabelText("E-post"));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(showSnackbar).toHaveBeenCalledWith(
        "Publiceringsval sparade",
        "success",
      ),
    );
    expect(updateConsent).toHaveBeenCalledWith({ email: true });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("sends all four keys when the member has never answered", async () => {
    // {} = "ej angivet" in the Koharen export — the first answer must record
    // every key, even when the member leaves them all off.
    vi.mocked(updateConsent).mockResolvedValue({
      ok: true,
      consent: { ...initial, email: true },
      answered: true,
    });
    renderIt(false, false);
    fireEvent.click(screen.getByLabelText("E-post"));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(updateConsent).toHaveBeenCalled());
    expect(updateConsent).toHaveBeenCalledWith({
      name: true,
      phone: false,
      email: true,
      address: false,
    });
  });

  it("does not PATCH an answered card when nothing moved", async () => {
    vi.mocked(updateConsent).mockResolvedValue({
      ok: true,
      consent: initial,
      answered: true,
    });
    renderIt();
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(showSnackbar).toHaveBeenCalledWith(
        "Publiceringsval sparade",
        "success",
      ),
    );
    expect(updateConsent).not.toHaveBeenCalled();
  });

  it("diffs the next save against what the server acknowledged, not the refreshed prop", async () => {
    // Another tab withdraws E-post while this one is open. This tab
    // saves Telefon; the backend merges and answers email=false, and the page's
    // props refresh. The next save must not turn the email=true this tab
    // mounted with into a "dirty" key and put the withdrawal back.
    const mounted = { name: true, phone: false, email: true, address: false };
    const merged = { name: true, phone: true, email: false, address: false };
    vi.mocked(updateConsent).mockResolvedValue({
      ok: true,
      consent: merged,
      answered: true,
    });
    const view = render(
      <ThemeProvider theme={stambokenTheme}>
        <PubliceringClient initial={mounted} answered />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByLabelText("Telefon"));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(updateConsent).toHaveBeenCalledWith({ phone: true }),
    );
    // The switches now show the server's answer, withdrawal included.
    await waitFor(() =>
      expect(
        (screen.getByLabelText("E-post") as HTMLInputElement).checked,
      ).toBe(false),
    );
    view.rerender(
      <ThemeProvider theme={stambokenTheme}>
        <PubliceringClient initial={merged} answered />
      </ThemeProvider>,
    );
    vi.mocked(updateConsent).mockClear();
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(showSnackbar).toHaveBeenCalledTimes(2));
    expect(updateConsent).not.toHaveBeenCalled();
  });

  it("sends only the moved switch on the save after the first answer", async () => {
    // The first answer records all four keys; from then on this tab is
    // "answered" even before the props refresh, so the next save is partial.
    vi.mocked(updateConsent).mockResolvedValue({
      ok: true,
      consent: { ...initial, email: true },
      answered: true,
    });
    renderIt(false, false);
    fireEvent.click(screen.getByLabelText("E-post"));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(updateConsent).toHaveBeenCalledWith({
        name: true,
        phone: false,
        email: true,
        address: false,
      }),
    );
    fireEvent.click(screen.getByLabelText("Telefon"));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(updateConsent).toHaveBeenCalledTimes(2));
    expect(updateConsent).toHaveBeenLastCalledWith({ phone: true });
  });

  it("locks every switch and Spara when readOnly", () => {
    renderIt(true);
    expect(
      screen.getByText(
        "Endast huvudmedlemmen kan ändra medlemskapets uppgifter.",
      ),
    ).toBeDefined();
    for (const label of ["Namn", "Telefon", "E-post", "Adress"]) {
      expect((screen.getByLabelText(label) as HTMLInputElement).disabled).toBe(
        true,
      );
    }
    expect(
      (screen.getByRole("button", { name: "Spara" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});
