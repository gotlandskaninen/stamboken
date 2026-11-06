import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { stambokenTheme } from "@/theme/stamboken";
import type { UserContext } from "@/lib/user-context";

// Mock useSnackbar and useNotifications
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: vi.fn() }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification: vi.fn() }),
}));

// Mock server actions
vi.mock("@/app/(app)/stamboken/(dashboard)/profil/actions", () => ({
  updateProfilePicture: vi.fn(),
  updateSettings: vi.fn(),
}));

import { KontoCard } from "@/app/(app)/stamboken/(dashboard)/profil/KontoCard";

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={stambokenTheme}>{ui}</ThemeProvider>);
}

const mockUser: UserContext = {
  id: 1,
  email: "test@example.com",
  fullname: "Test User",
  username: "testuser",
  validated: true,
  is_admin: false,
  is_manager: null,
  is_owner: ["G1274"],
  is_matrikel_admin: false,
  profile_picture: null,
  google_picture: "https://example.com/pic.jpg",
  google_name: "Test Google",
  google_email: "google@example.com",
  use_google_picture: false,
  v2_prod_access: false,
};

afterEach(cleanup);

describe("KontoCard", () => {
  it("renders user display name", () => {
    renderWithTheme(<KontoCard user={mockUser} />);
    // Heading and the "Fullständigt namn" row both carry the display name
    expect(screen.getAllByText("Test Google").length).toBeGreaterThan(0);
    expect(screen.getByText("Fullständigt namn")).toBeDefined();
  });

  it("renders user email", () => {
    renderWithTheme(<KontoCard user={mockUser} />);
    expect(screen.getAllByText("test@example.com").length).toBeGreaterThan(0);
  });

  it("shows Google email when different from primary", () => {
    renderWithTheme(<KontoCard user={mockUser} />);
    expect(screen.getByText(/google@example\.com/)).toBeDefined();
  });

  it("renders owner badge", () => {
    renderWithTheme(<KontoCard user={mockUser} />);
    expect(screen.getByText("Ägare G1274")).toBeDefined();
  });

  it("shows validated status", () => {
    renderWithTheme(<KontoCard user={mockUser} />);
    expect(screen.getByText("Validerad")).toBeDefined();
  });

  it("shows Google picture toggle when google_picture exists", () => {
    renderWithTheme(<KontoCard user={mockUser} />);
    expect(screen.getByText("Använd Google-profilbild")).toBeDefined();
  });

  it("hides Google picture toggle when no google_picture", () => {
    renderWithTheme(<KontoCard user={{ ...mockUser, google_picture: null }} />);
    expect(screen.queryByText("Använd Google-profilbild")).toBeNull();
  });

  it("shows not-validated warning when user is not validated", () => {
    renderWithTheme(<KontoCard user={{ ...mockUser, validated: false }} />);
    expect(screen.getByText("Inte validerad")).toBeDefined();
    expect(screen.getByText(/För att bli validerad/)).toBeDefined();
    expect(screen.getByRole("link", { name: "Gå kursen nu" })).toBeDefined();
  });

  it("shows admin badge when user is admin", () => {
    renderWithTheme(<KontoCard user={{ ...mockUser, is_admin: true }} />);
    expect(screen.getByText("Administratör")).toBeDefined();
  });

  it("shows manager badge when user manages a genebank", () => {
    renderWithTheme(<KontoCard user={{ ...mockUser, is_manager: [1] }} />);
    expect(screen.getByText("Genbanksansvarig")).toBeDefined();
  });

  it("offers the upload button and the Google Workspace hint", () => {
    renderWithTheme(<KontoCard user={mockUser} />);
    expect(
      screen.getByRole("button", { name: "Ladda upp bild" }),
    ).toBeDefined();
    expect(
      screen.getByText(
        "Hanteras via Google Workspace. Kontakta admin för ändringar.",
      ),
    ).toBeDefined();
  });
});
