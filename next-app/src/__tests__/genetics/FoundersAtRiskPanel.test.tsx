import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import type { FounderAtRisk } from "@/redux/api/apiSlice";

const atRiskQuery = vi.fn();

vi.mock("@/redux/api/apiSlice", () => ({
  useFetchFoundersAtRiskQuery: () => atRiskQuery(),
}));

import FoundersAtRiskPanel, {
  founderOrder,
} from "@/components/genetics/FoundersAtRiskPanel";

const founder = (
  founder_id: string,
  risk_level: FounderAtRisk["risk_level"],
  extra: Partial<FounderAtRisk> = {},
): FounderAtRisk => ({
  founder_id,
  risk_level,
  n_carriers: 0,
  avg_contribution: 0.01,
  allele_retention: null,
  carrier_ids: [],
  recoverable_carriers: [],
  ...extra,
});

const founders = [
  founder("G9001-1", "lost"),
  founder("G9001-2", "ok"),
  founder("G9001-3", "monitor"),
  founder("G9001-4", "critical", {
    n_carriers: 1,
    carrier_ids: ["G9002-2401"],
    recoverable_carriers: ["G9003-2302"],
  }),
  founder("G9001-5", "warning"),
  founder("G9001-6", "ok"),
];

const rowIds = () =>
  screen
    .getAllByRole("row")
    .slice(1)
    .map((r) => r.querySelector("td")?.textContent);

describe("FoundersAtRiskPanel", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("orders 1 bärare kvar, 2–3 bärare, Liten andel, then Ok and Ingen bärare", () => {
    expect(founderOrder(founders).map((f) => f.risk_level)).toEqual([
      "critical",
      "warning",
      "monitor",
      "ok",
      "ok",
      "lost",
    ]);
  });

  it("folds Ok and Ingen bärare behind a toggle with their counts", () => {
    atRiskQuery.mockReturnValue({ data: founders, isLoading: false });
    render(
      <ThemeProvider theme={createTheme()}>
        <FoundersAtRiskPanel genebankId={1} />
      </ThemeProvider>,
    );
    expect(rowIds()).toEqual(["G9001-4", "G9001-5", "G9001-3"]);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Visa också Ok (2) och Ingen bärare (1)",
      }),
    );
    expect(rowIds()).toEqual([
      "G9001-4",
      "G9001-5",
      "G9001-3",
      "G9001-2",
      "G9001-6",
      "G9001-1",
    ]);
    fireEvent.click(
      screen.getByRole("button", { name: "Dölj Ok och Ingen bärare" }),
    );
    expect(rowIds()).toHaveLength(3);
  });

  it("links the founderdjur, its carriers and its possible carriers to the rabbit page", () => {
    atRiskQuery.mockReturnValue({ data: founders, isLoading: false });
    render(
      <ThemeProvider theme={createTheme()}>
        <FoundersAtRiskPanel genebankId={1} />
      </ThemeProvider>,
    );
    for (const n of ["G9001-4", "G9002-2401", "G9003-2302"]) {
      expect(screen.getByRole("link", { name: n }).getAttribute("href")).toBe(
        `/stamboken/individ/${n}`,
      );
    }
  });
});
