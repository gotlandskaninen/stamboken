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

  const rows = () => screen.queryByText("Kritisk (1)");
  const failedAlert = () =>
    screen.queryByText(/Kunde inte hämta prioriteringsdata/);
  const staleNote = () => screen.queryByText(/Kunde inte uppdatera/);

  it("refetches on mount and keeps the cached rows on screen meanwhile", () => {
    renderTab({ data: cached, currentData: cached, isFetching: true });
    expect(prioritiesQuery).toHaveBeenCalledWith(1, {
      refetchOnMountOrArgChange: true,
    });
    expect(banner()).toBeNull();
    expect(rows()).toBeTruthy();
  });

  it("shows the banner only while there is no data yet", () => {
    renderTab({
      data: undefined,
      currentData: undefined,
      isLoading: true,
      isFetching: true,
    });
    expect(banner()).toBeTruthy();
  });

  it("does not show the previous genebank's rows while the new one loads", () => {
    // After a switch A→B, data is still A's until B answers (and isLoading is false).
    renderTab({
      data: cached,
      currentData: undefined,
      isLoading: false,
      isFetching: true,
    });
    expect(banner()).toBeTruthy();
    expect(rows()).toBeNull();
  });

  it("keeps the cached rows with a note when a refetch fails", () => {
    renderTab({
      data: cached,
      currentData: cached,
      isFetching: false,
      error: { status: 500 },
    });
    expect(failedAlert()).toBeNull();
    expect(staleNote()).toBeTruthy();
    expect(rows()).toBeTruthy();
  });

  it("shows the error when the failed genebank has no data of its own", () => {
    renderTab({
      data: cached,
      currentData: undefined,
      isFetching: false,
      error: { status: 500 },
    });
    expect(failedAlert()).toBeTruthy();
    expect(rows()).toBeNull();
  });

  it("hides the cached rows after a 403 or 401", () => {
    const denied = { data: cached, currentData: cached, isFetching: false };
    renderTab({ ...denied, error: { status: 403 } });
    expect(failedAlert()).toBeTruthy();
    expect(rows()).toBeNull();
    cleanup();
    renderTab({ ...denied, error: { status: 401 } });
    expect(failedAlert()).toBeNull(); // the session-expired flow takes over, as before
    expect(staleNote()).toBeNull();
    expect(rows()).toBeNull();
  });
});
