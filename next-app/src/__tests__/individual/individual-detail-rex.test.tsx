import React from "react";
import { describe, it, expect, afterEach, beforeAll, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import type { Individual } from "@/redux/api/apiSlice";

const { updateIndividual } = vi.hoisted(() => ({
  updateIndividual: vi.fn(),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/individ/[number]/actions", () => ({
  updateIndividual,
  getGenebankHerds: vi.fn(),
  voidHerdTracking: vi.fn(),
  correctHerdTracking: vi.fn(),
  undoHerdTrackingOperation: vi.fn(),
}));
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/individ/[number]/audit-types",
  () => ({}),
);
vi.mock("@/app/(app)/stamboken/(dashboard)/min-besattning/actions", () => ({
  getColors: vi.fn().mockResolvedValue(null),
}));
vi.mock("@/components/audit/AuditTimeline", () => ({ default: () => null }));
vi.mock("@/components/herd/IndividualCard", () => ({
  IndividualCard: () => null,
}));
vi.mock("@/components/individual/PedigreeSection", () => ({
  PedigreeSection: () => null,
}));
vi.mock("@/components/individual/HealthSection", () => ({
  HealthSection: () => null,
}));
vi.mock("@/components/individual/HerdHistorySection", () => ({
  HerdHistorySection: () => null,
}));
vi.mock("@/components/individual/NotesSection", () => ({
  NotesSection: () => null,
}));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams("edit=true"),
}));
vi.mock("@/lib/user-context", () => ({
  useUser: () => ({ is_admin: true }),
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: vi.fn() }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification: vi.fn() }),
}));

import { IndividualDetail } from "@/app/(app)/stamboken/(dashboard)/individ/[number]/individual-detail";

beforeAll(async () => {
  await import("@/i18n");
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
  localStorage.clear();
});

const individual = {
  id: 1,
  number: "G1-2401",
  herd: "G1",
  genebank_id: 1,
  alive: true,
  rex: false,
} as Individual;

const ui = (ind: Individual) => (
  <ThemeProvider theme={createTheme()}>
    <IndividualDetail individual={ind} history={null} />
  </ThemeProvider>
);

describe("individual-detail päls", () => {
  it("sparar rex och visar den efter omläsning", async () => {
    updateIndividual.mockResolvedValue({ success: true });
    const { rerender } = render(ui(individual));
    fireEvent.click(screen.getByRole("radio", { name: "Rex" }));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(updateIndividual).toHaveBeenCalledWith(
        "G1-2401",
        expect.objectContaining({ rex: true }),
      ),
    );
    // Omläsning: servern ger tillbaka individen med rex true
    rerender(ui({ ...individual, rex: true }));
    await waitFor(() => expect(screen.getByText("Rex")).toBeDefined());
    expect(screen.queryByRole("radio")).toBeNull(); // redigeringen stängd efter sparat
  });
});
