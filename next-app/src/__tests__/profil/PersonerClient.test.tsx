import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { stambokenTheme } from "@/theme/stamboken";

// Mutation feedback goes through the app-wide snackbar + notification hooks
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

// Mock the server actions the components in this file import
vi.mock("@/app/(app)/stamboken/(dashboard)/profil/actions", () => ({
  addMyPerson: vi.fn(),
  removeMyPerson: vi.fn(),
  createMyGrant: vi.fn(),
  renewMyGrant: vi.fn(),
  revokeMyGrant: vi.fn(),
  updateContact: vi.fn(),
  updateConsent: vi.fn(),
}));

import { removeMyPerson } from "@/app/(app)/stamboken/(dashboard)/profil/actions";
import { PersonerClient } from "@/app/(app)/stamboken/(dashboard)/profil/PersonerClient";
import type {
  MyHerd,
  MyPerson,
} from "@/app/(app)/stamboken/(dashboard)/profil/types";

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={stambokenTheme}>{ui}</ThemeProvider>);
}

const persons: MyPerson[] = [
  {
    id: 1,
    first_name: "Anna",
    last_name: "Andersson",
    email: "anna@example.com",
    phone: null,
    role: "huvudmedlem",
    grants: [],
  },
  {
    id: 2,
    first_name: "Sam",
    last_name: "Svensson",
    email: null,
    phone: null,
    role: "skotare",
    grants: [
      {
        id: 9,
        herd_id: 3,
        herd: "G6",
        valid_until: "2099-01-01",
        revoked_at: null,
      },
    ],
  },
];

const herds: MyHerd[] = [{ id: 3, herd: "G6", herd_name: "Testgård" }];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PersonerClient", () => {
  it("lists persons with Swedish role labels for the main member", () => {
    renderWithTheme(
      <PersonerClient isMainMember persons={persons} herds={herds} />,
    );
    expect(screen.getByText("Anna Andersson")).toBeDefined();
    expect(screen.getByText("Huvudmedlem")).toBeDefined();
    expect(screen.getByText("Sam Svensson")).toBeDefined();
    expect(screen.getByText("Skötare")).toBeDefined();
  });

  it("shows all self-service actions for the main member", () => {
    renderWithTheme(
      <PersonerClient isMainMember persons={persons} herds={herds} />,
    );
    expect(
      screen.getByRole("button", { name: "Lägg till person" }),
    ).toBeDefined();
    expect(screen.getAllByRole("button", { name: "Ge åtkomst" })).toHaveLength(
      2,
    );
    expect(screen.getByRole("button", { name: "Förnya" })).toBeDefined();
    expect(screen.getByRole("button", { name: "Återkalla" })).toBeDefined();
    // "Ta bort" only on the non-main rows — never on the huvudmedlem row
    expect(screen.getAllByRole("button", { name: "Ta bort" })).toHaveLength(1);
  });

  it("shows the grant status with its expiry date", () => {
    renderWithTheme(
      <PersonerClient isMainMember persons={persons} herds={herds} />,
    );
    expect(screen.getByText("G6 t.o.m. 2099-01-01")).toBeDefined();
  });

  it("preselects the only herd when the grant dialog opens", () => {
    renderWithTheme(
      <PersonerClient isMainMember persons={persons} herds={herds} />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Ge åtkomst" })[0]);
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("combobox").textContent).toContain(
      "G6 — Testgård",
    );
    expect(
      (
        within(dialog).getByRole("button", {
          name: "Ge åtkomst",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  it("leaves the herd unselected when there is more than one", () => {
    renderWithTheme(
      <PersonerClient
        isMainMember
        persons={persons}
        herds={[...herds, { id: 4, herd: "G7", herd_name: null }]}
      />,
    );
    fireEvent.click(screen.getAllByRole("button", { name: "Ge åtkomst" })[0]);
    const dialog = screen.getByRole("dialog");
    // Empty MUI selects render a zero-width space, so assert on the herds
    expect(within(dialog).getByRole("combobox").textContent).not.toContain(
      "G6",
    );
    expect(
      (
        within(dialog).getByRole("button", {
          name: "Ge åtkomst",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("reports a failed removal through snackbar and notification", async () => {
    vi.mocked(removeMyPerson).mockResolvedValue({
      ok: false,
      error: "Personen kunde inte tas bort.",
    });
    renderWithTheme(
      <PersonerClient isMainMember persons={persons} herds={herds} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Ta bort" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    await waitFor(() =>
      expect(showSnackbar).toHaveBeenCalledWith(
        "Personen kunde inte tas bort.",
        "error",
      ),
    );
    expect(addNotification).toHaveBeenCalledWith({
      title: "Kunde inte ta bort personen",
      message: "Personen kunde inte tas bort.",
      type: "error",
    });
    // No inline Alert left on the page
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("renders a read-only own entry for non-main persons", () => {
    renderWithTheme(
      <PersonerClient isMainMember={false} persons={[persons[1]]} herds={[]} />,
    );
    expect(screen.getByText(/Sam Svensson/)).toBeDefined();
    expect(screen.getByText(/Skötare/)).toBeDefined();
    expect(screen.getByText("G6 t.o.m. 2099-01-01")).toBeDefined();
    expect(
      screen.getByText(
        "Kontakta huvudmedlemmen för ändringar av medlemskapet.",
      ),
    ).toBeDefined();
    expect(
      screen.queryByRole("button", { name: "Lägg till person" }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: "Ta bort" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Återkalla" })).toBeNull();
  });
});
