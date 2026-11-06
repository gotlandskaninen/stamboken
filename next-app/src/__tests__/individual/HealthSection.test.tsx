import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
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
