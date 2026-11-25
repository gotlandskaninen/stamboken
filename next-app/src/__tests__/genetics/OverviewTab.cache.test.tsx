import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const metricsQuery = vi.fn();
const foundersQuery = vi.fn();

vi.mock("@/redux/api/apiSlice", () => ({
  useFetchPopulationMetricsQuery: (...args: unknown[]) => metricsQuery(...args),
  useFetchFounderStatisticsQuery: (...args: unknown[]) =>
    foundersQuery(...args),
  useFetchFoundersAtRiskQuery: () => ({ isFetching: false }),
  useFetchGeneticsTrendsQuery: () => ({ isFetching: false }),
}));
vi.mock("@/components/genetics/TrendChart", () => ({ default: () => null }));
vi.mock("@/components/genetics/FoundersAtRiskPanel", () => ({
  default: () => null,
}));

import OverviewTab from "@/components/genetics/OverviewTab";
import { ModeProvider } from "@/lib/mode-context";

describe("OverviewTab", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("never mixes the new genebank's metrics with the previous one's founder statistics", () => {
    // After a switch A→B: B's metrics have arrived, B's founder statistics have not.
    const metricsB = { n_active: 7 };
    metricsQuery.mockReturnValue({
      data: metricsB,
      currentData: metricsB,
      isFetching: false,
    });
    foundersQuery.mockReturnValue({
      data: { n_founders: 3 },
      currentData: undefined,
      isFetching: true,
    });
    render(
      <ThemeProvider theme={createTheme()}>
        <ModeProvider mode="prod">
          <OverviewTab genebankId={2} />
        </ModeProvider>
      </ThemeProvider>,
    );
    expect(screen.getByText(/Beräknar genetiska nyckeltal/)).toBeTruthy();
    expect(screen.queryByText("Aktiva individer")).toBeNull();
  });
});
