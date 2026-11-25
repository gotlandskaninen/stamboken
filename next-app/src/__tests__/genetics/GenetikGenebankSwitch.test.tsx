import React from "react";
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { stambokenTheme } from "@/theme/stamboken";

// Answers per genebank; a missing entry is a request still in flight.
const responses = vi.hoisted(() => ({
  metrics: new Map<number, unknown>(),
  founders: new Map<number, unknown>(),
  atRisk: new Map<number, unknown>(),
  trends: new Map<number, unknown>(),
  priorities: new Map<number, unknown>(),
}));

// The genetics hooks take the rendered mode with the genebank (ModeProvider in the app).
vi.mock("@/lib/mode-context", () => ({ useMode: () => "prod" }));

vi.mock("@/redux/api/apiSlice", async () => {
  const { useRef } = await import("react");
  // Like RTK Query: `data` keeps the last result while a new argument loads,
  // `currentData` is only ever the current argument's.
  const hook =
    (name: keyof typeof responses) =>
    ({ genebankId }: { genebankId: number }) => {
      const last = useRef<unknown>(undefined);
      const now = responses[name].get(genebankId);
      if (now !== undefined) last.current = now;
      return {
        data: last.current,
        currentData: now,
        isLoading: last.current === undefined,
        isFetching: now === undefined,
        refetch: () => {},
      };
    };
  return {
    useFetchPopulationMetricsQuery: hook("metrics"),
    useFetchFounderStatisticsQuery: hook("founders"),
    useFetchFoundersAtRiskQuery: hook("atRisk"),
    useFetchGeneticsTrendsQuery: hook("trends"),
    useFetchGeneticPrioritiesQuery: hook("priorities"),
  };
});

// The URL feeds useSearchParams, as in Next; pushState is announced so the double re-reads it.
vi.mock("next/navigation", async () => {
  const { useMemo, useSyncExternalStore } = await import("react");
  const subscribe = (onChange: () => void) => {
    window.addEventListener("popstate", onChange);
    window.addEventListener("test-pushstate", onChange);
    return () => {
      window.removeEventListener("popstate", onChange);
      window.removeEventListener("test-pushstate", onChange);
    };
  };
  return {
    useSearchParams: () => {
      const search = useSyncExternalStore(
        subscribe,
        () => window.location.search,
      );
      return useMemo(() => new URLSearchParams(search), [search]);
    },
  };
});
// Avelsprioritet reads the logged work-list route (useWorkList), with the same
// keep-the-last-result behaviour as the RTK double above, in the view's mode.
vi.mock("@/components/genetics/workList", async (original) => {
  const { useRef } = await import("react");
  return {
    ...(await original<typeof import("@/components/genetics/workList")>()),
    useWorkList: (genebankId: number) => {
      const last = useRef<unknown>(undefined);
      const now = responses.priorities.get(genebankId);
      if (now !== undefined) last.current = now;
      return {
        data: last.current,
        isLoading: last.current === undefined,
        refetch: () => {},
      };
    },
  };
});
vi.mock("@/lib/mode-context", () => ({ useMode: () => "prod" }));
vi.mock("@/hooks/useAuth", () => ({
  default: () => ({ user: { is_admin: true, is_manager: [1] } }),
}));
vi.mock("next/dynamic", () => ({ default: () => () => null }));
// jsdom has no layout, so the real grid renders no cells: list the rabbits' numbers instead.
vi.mock("@mui/x-data-grid", () => ({
  DataGrid: ({ rows }: { rows: { individual_id: string }[] }) => (
    <ul>
      {rows.map((r) => (
        <li key={r.individual_id}>{r.individual_id}</li>
      ))}
    </ul>
  ),
}));
vi.mock("@/components/genetics/BreedingSuggestionsTab", () => ({
  default: () => null,
}));

import GenetikPage from "@/app/(app)/stamboken/(dashboard)/genetik/page";

const metrics = (mk: number) => ({
  n_active: 40,
  effective_population_size: 60,
  ne_se: 3,
  mean_kinship: mk,
  mean_inbreeding: 0.01,
  delta_f: 0.005,
  reference_start: "2025-01-01",
});
const founders = {
  n_founders: 9,
  founder_equivalents: 6.2,
  proportional_loss: 0.02,
  top_founders: [],
  population_size: 40,
};
const row = (founder_id: string) => ({
  founder_id,
  risk_level: "ok",
  n_carriers: 5,
  avg_contribution: 0.1,
  allele_retention: null,
  carrier_ids: [],
});
const year = (y: number, mk: number) => ({
  year: y,
  snapshot_date: `${y + 1}-04-01`,
  population_size: 50,
  active_count: 40,
  mean_inbreeding: 0.01,
  mean_kinship: mk,
  effective_population_size: 50,
  ne_se: 3,
  ne_n: 40,
  founder_equivalents: 6,
  data_quality: "high",
});

const pushState = window.history.pushState.bind(window.history);

describe("Genetik page, switching genebank", () => {
  beforeEach(() => {
    vi.spyOn(window.history, "pushState").mockImplementation((...args) => {
      pushState(...args);
      window.dispatchEvent(new Event("test-pushstate"));
    });
    window.history.replaceState(null, "", "/stamboken/genetik");
    for (const m of Object.values(responses)) m.clear();
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  it("never shows the old genebank's years or founderdjur beside the new MK", () => {
    responses.metrics.set(1, metrics(0.012));
    responses.founders.set(1, founders);
    responses.atRisk.set(1, [row("G1"), row("G2")]);
    responses.trends.set(1, [year(2024, 0.011), year(2025, 0.012)]);
    const page = () => (
      <ThemeProvider theme={stambokenTheme}>
        <GenetikPage />
      </ThemeProvider>
    );
    const { rerender } = render(page());
    expect(
      screen.getByText("2024: 1,1 % · 2025: 1,2 % (stängda år)"),
    ).toBeDefined();
    expect(screen.getByText(/räknat på 2 founderdjur/)).toBeDefined();

    // Mellerud's metrics are in; its trend and founderdjur are still on their way.
    responses.metrics.set(2, metrics(0.05));
    responses.founders.set(2, founders);
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "Mellerudskanin" }));

    expect(screen.getByText("5,0 %")).toBeDefined();
    expect(screen.queryByText(/2024: 1,1 %/)).toBeNull();
    expect(screen.queryByText(/räknat på 2 founderdjur/)).toBeNull();

    responses.trends.set(2, [year(2024, 0.048), year(2025, 0.05)]);
    responses.atRisk.set(2, [row("M1")]);
    rerender(page());
    expect(
      screen.getByText("2024: 4,8 % · 2025: 5,0 % (stängda år)"),
    ).toBeDefined();
    expect(screen.getByText(/räknat på 1 founderdjur/)).toBeDefined();
  });

  it("never lists the old genebank's rabbits under Avelsprioritet", () => {
    const rabbit = (individual_id: string) => ({
      individual_id,
      priority: "critical",
      reasons: [],
      genetic_value_score: 90,
      genome_uniqueness: 0.1,
    });
    responses.metrics.set(1, metrics(0.012));
    responses.founders.set(1, founders);
    responses.priorities.set(1, [rabbit("G1-2301")]);
    const page = () => (
      <ThemeProvider theme={stambokenTheme}>
        <GenetikPage />
      </ThemeProvider>
    );
    const { rerender } = render(page());
    fireEvent.click(screen.getByRole("tab", { name: "Avelsprioritet" }));
    expect(screen.getByText("G1-2301")).toBeDefined();

    // Mellerud's list is still being computed.
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("option", { name: "Mellerudskanin" }));
    expect(screen.queryByText("G1-2301")).toBeNull();

    responses.priorities.set(2, [rabbit("M1-2401")]);
    rerender(page());
    expect(screen.getByText("M1-2401")).toBeDefined();
    expect(screen.queryByText("G1-2301")).toBeNull();
  });
});
