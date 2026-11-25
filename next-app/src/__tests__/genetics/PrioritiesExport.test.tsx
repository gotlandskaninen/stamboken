import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const downloadExport = vi.fn(async (url: string): Promise<string | null> => {
  void url;
  return null;
});

const modes = vi.hoisted(() => ({ view: "prod", cookie: "prod" }));
vi.mock("@/lib/mode", () => ({ readModeCookieClient: () => modes.cookie }));
vi.mock("@/lib/mode-context", () => ({ useMode: () => modes.view }));
vi.mock("@/components/genetics/workList", async (original) => ({
  ...(await original<typeof import("@/components/genetics/workList")>()),
  downloadExport: (url: string) => downloadExport(url),
  useWorkList: () => ({
    data: [
      {
        individual_id: "G9001-1",
        priority: "critical",
        reasons: [],
        genetic_value_score: 90,
        genome_uniqueness: 0.1,
      },
    ],
    isLoading: false,
    refetch: vi.fn(),
  }),
}));
// jsdom has no layout; the grid is not what this test is about.
vi.mock("@mui/x-data-grid", () => ({ DataGrid: () => null }));

import PrioritiesTab from "@/components/genetics/PrioritiesTab";

describe("Ladda ner CSV", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
    modes.view = modes.cookie = "prod";
  });

  const renderTab = () =>
    render(
      <ThemeProvider theme={createTheme()}>
        <PrioritiesTab genebankId={1} />
      </ThemeProvider>,
    );

  it("asks the server for the levels the chips have on, and for the per-besättning order", async () => {
    renderTab();
    fireEvent.click(screen.getByRole("button", { name: /^Övriga/ }));
    fireEvent.click(
      screen.getByRole("button", { name: "Sortera per besättning" }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner CSV" }));
    await waitFor(() =>
      expect(downloadExport).toHaveBeenCalledWith(
        "/api/v2/genetics/1/priorities.csv?levels=critical,important&per_herd=1",
      ),
    );
  });

  it("refuses in the client from a demo view, or when another tab has switched the cookie", async () => {
    modes.view = modes.cookie = "demo";
    renderTab();
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner CSV" }));
    expect(await screen.findByText(/där varje uttag loggas/)).toBeDefined();
    cleanup();

    modes.view = "prod";
    renderTab();
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner CSV" }));
    expect(await screen.findByText(/i en annan flik/)).toBeDefined();
    expect(downloadExport).not.toHaveBeenCalled();
  });

  it("shows the server's reason when the export is refused", async () => {
    downloadExport.mockResolvedValueOnce(
      "Exporten går bara att göra i den riktiga Stamboken, där varje uttag loggas.",
    );
    renderTab();
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner CSV" }));
    expect(await screen.findByText(/där varje uttag loggas/)).toBeDefined();
  });
});
