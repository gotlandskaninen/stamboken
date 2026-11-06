import React from "react";
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import KpiCard from "@/components/genetics/KpiCard";

const theme = createTheme();

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

describe("KpiCard", () => {
  it("renders title and value", () => {
    renderWithTheme(<KpiCard title="Test Title" value="42" />);
    expect(screen.getByText("Test Title")).toBeDefined();
    expect(screen.getByText("42")).toBeDefined();
  });

  it("renders subtitle when provided", () => {
    renderWithTheme(
      <KpiCard title="Ne" value="127.3" subtitle="Över rekommenderat" />,
    );
    expect(screen.getByText("Över rekommenderat")).toBeDefined();
  });

  it("renders without subtitle", () => {
    const { container } = renderWithTheme(
      <KpiCard title="Count" value="100" />,
    );
    expect(container.querySelector("h3")).toBeDefined();
  });

  it("accepts level prop without crashing", () => {
    renderWithTheme(
      <KpiCard title="MK" value="0.042" level="good" subtitle="Låg nivå" />,
    );
    expect(screen.getByText("0.042")).toBeDefined();
  });
});
