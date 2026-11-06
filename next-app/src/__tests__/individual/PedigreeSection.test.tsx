import React from "react";
import { describe, it, expect, afterEach, beforeAll } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import type { Individual, PedigreeNode } from "@/redux/api/apiSlice";
import { PedigreeSection } from "@/components/individual/PedigreeSection";

beforeAll(async () => {
  await import("@/i18n");
});

const theme = createTheme();

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

const mockIndividual = {
  number: "G1-2111",
  name: "TestKanin",
  mother: { number: "G1-1911", name: "Mamma", sex: "female" },
  father: { number: "G2-1711", name: "Pansen", sex: "male" },
  litter_size: 6,
  litter_size6w: 5,
} as Individual;

const mockPedigree: PedigreeNode = {
  id: 1,
  name: "TestKanin",
  number: "G1-2111",
  sex: "female",
  mother: {
    id: 2,
    name: "Mamma",
    number: "G1-1911",
    sex: "female",
    mother: null,
    father: null,
  },
  father: {
    id: 3,
    name: "Pansen",
    number: "G2-1711",
    sex: "male",
    mother: null,
    father: null,
  },
};

afterEach(cleanup);

describe("PedigreeSection", () => {
  it("renders section title", () => {
    renderWithTheme(
      <PedigreeSection individual={mockIndividual} pedigree={mockPedigree} />,
    );
    expect(screen.getByText("Släktträd")).toBeDefined();
  });

  it("renders pedigree tree when data is provided", () => {
    renderWithTheme(
      <PedigreeSection individual={mockIndividual} pedigree={mockPedigree} />,
    );
    expect(screen.getByTestId("pedigree-tree")).toBeDefined();
  });

  it("shows error alert when pedigree is null", () => {
    renderWithTheme(
      <PedigreeSection individual={mockIndividual} pedigree={null} />,
    );
    expect(screen.queryByTestId("pedigree-tree")).toBeNull();
    expect(screen.getByRole("alert")).toBeDefined();
  });

  it("renders litter size info", () => {
    renderWithTheme(
      <PedigreeSection individual={mockIndividual} pedigree={mockPedigree} />,
    );
    expect(screen.getByText(/Kullstorlek: 6/)).toBeDefined();
    expect(screen.getByText(/vid 6v: 5/)).toBeDefined();
  });

  it("hides litter size when not available", () => {
    const noLitter = {
      ...mockIndividual,
      litter_size: null,
      litter_size6w: null,
    };
    renderWithTheme(
      <PedigreeSection individual={noLitter as Individual} pedigree={null} />,
    );
    expect(screen.queryByText(/Kullstorlek/)).toBeNull();
  });
});
