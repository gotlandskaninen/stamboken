import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import "@/i18n";
import { IdentitySection } from "@/components/individual/IdentitySection";
import type { Individual } from "@/redux/api/apiSlice";

vi.mock("@/app/(app)/stamboken/(dashboard)/min-besattning/actions", () => ({
  getColors: vi.fn().mockResolvedValue(null),
}));

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

  it("IdentitySection visar numret före namnet", () => {
    renderWithTheme(
      <IdentitySection
        individual={{ ...mockIndividual, color: "Viltgrå", color_id: 22 }}
        isEditing={false}
        formData={{}}
        onFieldChange={() => {}}
      />,
    );
    expect(screen.getByText("22 Viltgrå")).toBeDefined();
  });

  it("redigeringsläget visar den sparade färgen även när listan saknas", () => {
    renderWithTheme(
      <IdentitySection
        individual={{
          ...mockIndividual,
          color: "Viltgrå",
          color_id: 22,
          herd: "G1",
        }}
        isEditing={true}
        formData={{}}
        onFieldChange={() => {}}
      />,
    );
    expect((screen.getByRole("combobox") as HTMLInputElement).value).toBe(
      "22 Viltgrå",
    );
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

  it("Päls: valet Rex anropar onFieldChange med true, Normal med false", () => {
    const onFieldChange = vi.fn();
    const { rerender } = renderWithTheme(
      <IdentitySection
        individual={{ ...mockIndividual, rex: false }}
        isEditing={true}
        formData={{}}
        onFieldChange={onFieldChange}
      />,
    );
    expect(screen.getByText("Päls")).toBeDefined();
    fireEvent.click(screen.getByRole("radio", { name: "Rex" }));
    expect(onFieldChange).toHaveBeenLastCalledWith("rex", true);
    rerender(
      <ThemeProvider theme={theme}>
        <IdentitySection
          individual={{ ...mockIndividual, rex: false }}
          isEditing={true}
          formData={{ rex: true }}
          onFieldChange={onFieldChange}
        />
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("radio", { name: "Normal" }));
    expect(onFieldChange).toHaveBeenLastCalledWith("rex", false);
  });

  it("Päls visas som text utanför redigering", () => {
    renderWithTheme(
      <IdentitySection
        individual={{ ...mockIndividual, rex: true }}
        isEditing={false}
        formData={{}}
        onFieldChange={() => {}}
      />,
    );
    expect(screen.getByText("Rex")).toBeDefined();
  });
});
