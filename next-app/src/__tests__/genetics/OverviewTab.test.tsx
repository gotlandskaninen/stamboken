import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const metricsQuery = vi.fn();
const foundersQuery = vi.fn();
const atRiskQuery = vi.fn();
const trendsQuery = vi.fn(() => ({ data: [] as object[], isLoading: false }));

// The answer is the current argument's own, as RTK Query's currentData after a fetch.
const own = (r: { data?: unknown; isLoading?: boolean }) => ({
  currentData: r.data,
  isFetching: Boolean(r.isLoading),
  ...r,
});

// The genetics hooks take the rendered mode with the genebank (ModeProvider in the app).
vi.mock("@/lib/mode-context", () => ({ useMode: () => "prod" }));

vi.mock("@/redux/api/apiSlice", () => ({
  useFetchPopulationMetricsQuery: () => own(metricsQuery()),
  useFetchFounderStatisticsQuery: () => own(foundersQuery()),
  useFetchFoundersAtRiskQuery: () => own(atRiskQuery()),
  useFetchGeneticsTrendsQuery: () => own(trendsQuery()),
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
  reference_start: "2025-01-01",
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
    expect(screen.getByText("stängda år: –")).toBeDefined(); // no closed year yet
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

  it("compares the two latest closed years on one rule, without a verdict", () => {
    trendsQuery.mockReturnValueOnce({
      data: [
        { year: 2023, mean_kinship: 0.022 },
        { year: 2024, mean_kinship: 0.0289 },
        { year: 2025, mean_kinship: 0.0302 },
      ],
      isLoading: false,
    });
    renderTab();
    expect(screen.getByText("2,6 %")).toBeDefined(); // today
    expect(
      screen.getByText("2024: 2,9 % · 2025: 3,0 % (stängda år)"),
    ).toBeDefined();
    cleanup();

    trendsQuery.mockReturnValueOnce({
      data: [{ year: 2025, mean_kinship: null }],
      isLoading: false,
    });
    renderTab();
    expect(screen.getByText("2025: – (stängt år)")).toBeDefined();
  });

  it("states the reference window's first day in Swedish", () => {
    renderTab();
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

  it("treats zeros without a date as a failed calculation, not an empty genebank", () => {
    renderTab({
      m: { ...metrics, n_active: 0, mean_kinship: 0, reference_start: null },
    });
    expect(
      screen.getByText(
        "Beräkningen gick inte att hämta. Försök igen om en stund.",
      ),
    ).toBeDefined();
    expect(screen.queryByText(/inga kaniner i beräkningen/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("shows an older API's answer (no reference_start) without the date", () => {
    const { reference_start: _absent, ...mainShaped } = metrics;
    renderTab({ m: { ...mainShaped, n_active: 40 } });
    expect(screen.getByText("40")).toBeDefined();
    expect(
      screen.getByText("levande, med intyg, i en aktiv besättning"),
    ).toBeDefined();
    expect(screen.queryByText(/Försök igen|gick inte att hämta/)).toBeNull();
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
