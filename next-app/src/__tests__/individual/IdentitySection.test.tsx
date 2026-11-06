import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { IdentitySection } from "@/components/individual/IdentitySection";
import type { Individual } from "@/redux/api/apiSlice";

const theme = createTheme();

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

const mockIndividual = {
  number: "G1274-2301",
  certificate: null,
  digital_certificate: "D-1234",
  color: "Svart",
  color_note: "Vit bröstfläck",
  eye_color: "Brun",
  claw_color: "Svart",
  belly_color: "Grå",
  hair_notes: "Normal",
  is_registered: true,
} as Individual;

afterEach(cleanup);

describe("IdentitySection", () => {
  it("renders color fields", () => {
    renderWithTheme(
      <IdentitySection
        individual={mockIndividual}
        isEditing={false}
        formData={{}}
        onFieldChange={() => {}}
      />,
    );
    expect(screen.getAllByText("Svart")).toHaveLength(2); // color + claw_color
    expect(screen.getByText("Vit bröstfläck")).toBeDefined();
  });

  it("shows empty fields with dash", () => {
    const emptyIndividual = {
      ...mockIndividual,
      eye_color: null,
      belly_color: null,
    } as Individual;
    renderWithTheme(
      <IdentitySection
        individual={emptyIndividual}
        isEditing={false}
        formData={{}}
        onFieldChange={() => {}}
      />,
    );
    // Empty fields should show dash instead of being hidden
    const dashes = screen.getAllByText("—");
    expect(dashes.length).toBeGreaterThanOrEqual(2);
  });
});
