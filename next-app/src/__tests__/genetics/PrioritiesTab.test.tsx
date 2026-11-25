import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const prioritiesQuery = vi.fn();

vi.mock("@/redux/api/apiSlice", () => ({
  useFetchGeneticPrioritiesQuery: (...args: unknown[]) =>
    prioritiesQuery(...args),
}));

import PrioritiesTab from "@/components/genetics/PrioritiesTab";

const theme = createTheme();
const cached = [
  {
    individual_id: "G1-1",
    priority: "critical",
    reasons: [],
    genetic_value_score: 1,
    genome_uniqueness: 0.5,
  },
];

function renderTab(state: Record<string, unknown>) {
  prioritiesQuery.mockReturnValue(state);
  return render(
    <ThemeProvider theme={theme}>
      <PrioritiesTab genebankId={1} />
    </ThemeProvider>,
  );
}

const banner = () => screen.queryByText(/Beräknar genetiska prioriteringar/);

describe("PrioritiesTab", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("refetches on mount and keeps the cached rows on screen meanwhile", () => {
    renderTab({
      data: cached,
      currentData: cached,
      isLoading: false,
      isFetching: true,
    });
    expect(prioritiesQuery).toHaveBeenCalledWith(1, {
      refetchOnMountOrArgChange: true,
    });
    expect(banner()).toBeNull();
    expect(screen.getByText("Kritisk (1)")).toBeTruthy();
  });

  it("shows the banner only while there is no data yet", () => {
    renderTab({ data: undefined, isLoading: true, isFetching: true });
    expect(banner()).toBeTruthy();
  });

  it("keeps the cached rows when the background refetch fails", () => {
    const error = { status: 500 };
    renderTab({ data: cached, currentData: cached, isLoading: false, error });
    expect(screen.queryByText(/Kunde inte hämta prioriteringsdata/)).toBeNull();
    expect(screen.getByText("Kritisk (1)")).toBeTruthy();
  });

  it("shows the error when the failed genebank has no data of its own", () => {
    // After a genebank switch, data is still the previous genebank's.
    renderTab({
      data: cached,
      currentData: undefined,
      isLoading: false,
      error: { status: 500 },
    });
    expect(screen.getByText(/Kunde inte hämta prioriteringsdata/)).toBeTruthy();
  });
});
