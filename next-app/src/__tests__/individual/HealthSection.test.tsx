import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  within,
} from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { HealthSection } from "@/components/individual/HealthSection";
import type { Individual } from "@/redux/api/apiSlice";

const theme = createTheme();

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

const mockIndividual = {
  weights: [
    { date: "2024-03-15", weight: 3.2 },
    { date: "2023-09-01", weight: 2.8 },
  ],
  bodyfat: [{ date: "2024-03-15", bodyfat: "normal" as const }],
  inbreeding: "8.20",
  MK: "4.10",
} as Individual;

afterEach(cleanup);

describe("HealthSection", () => {
  it("renders latest weight and bodyfat", () => {
    renderWithTheme(<HealthSection individual={mockIndividual} />);
    expect(screen.getAllByText(/3\.2 kg/).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("Normal")).toBeDefined();
  });

  it("labels hull as on the paper form", () => {
    const withBodyfat = (bodyfat: "low" | "high") =>
      ({
        weights: [],
        bodyfat: [{ date: "2024-03-15", bodyfat }],
      }) as unknown as Individual;
    renderWithTheme(<HealthSection individual={withBodyfat("low")} />);
    expect(screen.getByText("Mager")).toBeDefined();
    cleanup();
    renderWithTheme(<HealthSection individual={withBodyfat("high")} />);
    expect(screen.getByText("Fet")).toBeDefined();
  });

  it("labels hull in the history as on the paper form", () => {
    const individual = {
      weights: [],
      bodyfat: [
        { date: "2024-03-15", bodyfat: "low" },
        { date: "2023-09-01", bodyfat: "high" },
      ],
    } as unknown as Individual;
    renderWithTheme(<HealthSection individual={individual} />);
    fireEvent.click(screen.getByText("Visa alla mätvärden"));
    const history = screen.getByText("Alla hullbedömningar")
      .nextElementSibling as HTMLElement;
    expect(within(history).getByText("Mager")).toBeDefined();
    expect(within(history).getByText("Fet")).toBeDefined();
  });

  it("shows expand button when history exists", () => {
    renderWithTheme(<HealthSection individual={mockIndividual} />);
    expect(screen.getByText("Visa alla mätvärden")).toBeDefined();
  });

  it("shows empty state when no data", () => {
    const emptyIndividual = {
      weights: [],
      bodyfat: [],
    } as unknown as Individual;
    renderWithTheme(<HealthSection individual={emptyIndividual} />);
    expect(screen.getByText("Inga mätvärden registrerade.")).toBeDefined();
  });
});
