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
  founder("G9001-7", "lost", { recoverable_carriers: ["G9004-2201"] }),
];

const renderPanel = (data: FounderAtRisk[]) => {
  atRiskQuery.mockReturnValue({ data, isLoading: false });
  render(
    <ThemeProvider theme={createTheme()}>
      <FoundersAtRiskPanel genebankId={1} />
    </ThemeProvider>,
  );
};

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

  it("orders 1 bärare kvar, Ingen bärare with possible carriers, 2–3 bärare, Liten andel, then the rest", () => {
    expect(founderOrder(founders).map((f) => f.founder_id)).toEqual([
      "G9001-4",
      "G9001-7",
      "G9001-5",
      "G9001-3",
      "G9001-2",
      "G9001-6",
      "G9001-1",
    ]);
  });

  it("folds only Ok and Ingen bärare without possible carriers, and the toggle counts them", () => {
    renderPanel(founders);
    expect(rowIds()).toEqual(["G9001-4", "G9001-7", "G9001-5", "G9001-3"]);

    fireEvent.click(
      screen.getByRole("button", {
        name: "Visa 3 till: Ok (2) och Ingen bärare (1)",
      }),
    );
    expect(rowIds()).toEqual([
      "G9001-4",
      "G9001-7",
      "G9001-5",
      "G9001-3",
      "G9001-2",
      "G9001-6",
      "G9001-1",
    ]);
    fireEvent.click(screen.getByRole("button", { name: "Dölj de 3" }));
    expect(rowIds()).toHaveLength(4);
  });

  it("says so in a line when everything is folded", () => {
    renderPanel([founder("G9001-2", "ok"), founder("G9001-1", "lost")]);
    expect(
      screen.getByText("Inget founderdjur behöver åtgärdas just nu."),
    ).toBeDefined();
    expect(screen.queryByRole("table")).toBeNull();
    expect(
      screen.getByRole("button", {
        name: "Visa 2 till: Ok (1) och Ingen bärare (1)",
      }),
    ).toBeDefined();
  });

  it("links the founderdjur, its carriers and its possible carriers to the rabbit page", () => {
    renderPanel(founders);
    for (const n of ["G9001-4", "G9002-2401", "G9003-2302", "G9004-2201"]) {
      expect(screen.getByRole("link", { name: n }).getAttribute("href")).toBe(
        `/stamboken/individ/${n}`,
      );
    }
  });
});
