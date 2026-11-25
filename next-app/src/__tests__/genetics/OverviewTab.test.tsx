import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const metricsQuery = vi.fn();
const foundersQuery = vi.fn();
const atRiskQuery = vi.fn();
const trendsQuery = vi.fn(() => ({ data: [] as object[], isLoading: false }));

vi.mock("@/redux/api/apiSlice", () => ({
  useFetchPopulationMetricsQuery: () => metricsQuery(),
  useFetchFounderStatisticsQuery: () => foundersQuery(),
  useFetchFoundersAtRiskQuery: () => atRiskQuery(),
  useFetchGeneticsTrendsQuery: () => trendsQuery(),
}));

import OverviewTab from "@/components/genetics/OverviewTab";

const refetch = vi.fn();

const metrics = {
  n_active: 221,
  effective_population_size: 75.4,
  ne_se: 5.2,
  mean_kinship: 0.0258,
  mean_inbreeding: 0.0251,
  delta_f: 0.0067,
};
const founderStats = {
  n_founders: 81,
  founder_equivalents: 26.31,
  proportional_loss: 0.0258,
  top_founders: [],
  population_size: 221,
};
const row = (founder_id: string, risk_level: string, n_carriers: number) => ({
  founder_id,
  risk_level,
  n_carriers,
  avg_contribution: 0.01,
  allele_retention: null,
  carrier_ids: [],
  recoverable_carriers: [],
});

function renderTab({
  m = metrics as object,
  f = founderStats as object,
  rows = [row("G1", "lost", 0), row("G2", "critical", 1), row("G3", "ok", 9)],
  error,
}: {
  m?: object;
  f?: object;
  rows?: object[];
  error?: object;
} = {}) {
  metricsQuery.mockReturnValue({
    data: error ? undefined : m,
    isLoading: false,
    error,
    refetch,
  });
  foundersQuery.mockReturnValue({
    data: error ? undefined : f,
    isLoading: false,
    refetch,
  });
  atRiskQuery.mockReturnValue({ data: rows, isLoading: false, refetch });
  return render(
    <ThemeProvider theme={createTheme()}>
      <OverviewTab genebankId={1} />
    </ThemeProvider>,
  );
}

describe("OverviewTab", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("shows each number once, in Swedish format, with one founderdjur count", () => {
    // getByText compares with the no-break spaces before % collapsed to spaces.
    renderTab();
    expect(screen.getByText("75 ± 5")).toBeDefined();
    expect(screen.getByText("26,3")).toBeDefined();
    expect(screen.getByText("2,6 %")).toBeDefined();
    expect(screen.getByText("förra året –")).toBeDefined(); // no closed year yet
    expect(screen.queryByText(/under 5|5–10|över 10/)).toBeNull();
    // The card and the table count the same founderdjur.
    expect(
      screen.getByText(
        "räknat på 2 founderdjur med bärare i beräkningen och på okända föräldrar",
      ),
    ).toBeDefined();
    expect(
      screen.getByText("Founderdjurens läge (3 founderdjur)"),
    ).toBeDefined();
    expect(screen.getByText("0,67 % · mål under 1 % (FAO)")).toBeDefined();
    expect(screen.queryByText(/Diversitetsförlust/)).toBeNull();
    expect(screen.queryByText(/81/)).toBeNull();
  });

  it("compares MK with the last closed year, without a verdict", () => {
    const lastYear = new Date().getFullYear() - 1;
    trendsQuery.mockReturnValueOnce({
      data: [
        { year: lastYear - 1, mean_kinship: 0.022 },
        { year: lastYear, mean_kinship: 0.0241 },
      ],
      isLoading: false,
    });
    renderTab();
    expect(screen.getByText("2,6 %")).toBeDefined();
    expect(screen.getByText("förra året 2,4 %")).toBeDefined();
    cleanup();

    trendsQuery.mockReturnValueOnce({
      data: [{ year: lastYear - 2, mean_kinship: 0.0241 }],
      isLoading: false,
    });
    renderTab();
    expect(screen.getByText(`år ${lastYear - 2} 2,4 %`)).toBeDefined();
  });

  it("states the reference window's first day in Swedish", () => {
    renderTab({ m: { ...metrics, reference_start: "2025-01-01" } });
    expect(
      screen.getByText(
        "levande, med intyg, i en aktiv besättning, rapporterade sedan 1 januari 2025",
      ),
    ).toBeDefined();
  });

  it("shows – and a sentence for an empty genebank, never a healthy zero", () => {
    renderTab({
      m: {
        ...metrics,
        n_active: 0,
        effective_population_size: null,
        ne_se: null,
        mean_kinship: 0,
        mean_inbreeding: 0,
        delta_f: null,
      },
      f: { ...founderStats, founder_equivalents: 0 },
      rows: [],
    });
    expect(
      screen.getByText(/inga kaniner i beräkningen för den här genbanken/),
    ).toBeDefined();
    expect(screen.getAllByText("–").length).toBeGreaterThanOrEqual(5);
    expect(screen.queryByText(/under 5/)).toBeNull();
    expect(screen.queryByText(/0,0/)).toBeNull();
  });

  it("names the cause of an error and retries", () => {
    renderTab({ error: { status: 403 } });
    expect(screen.getByText(/inte behörighet/)).toBeDefined();
    cleanup();

    renderTab({ error: { status: 401 } });
    expect(screen.getByText(/utloggad/)).toBeDefined();
    cleanup();

    renderTab({ error: { status: 500 } });
    expect(
      screen.getByText(
        "Beräkningen gick inte att hämta. Försök igen om en stund.",
      ),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(refetch).toHaveBeenCalled();
  });
});
