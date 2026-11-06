import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { NotesSection } from "@/components/individual/NotesSection";
import type { Individual } from "@/redux/api/apiSlice";

const theme = createTheme();

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

afterEach(cleanup);

describe("NotesSection", () => {
  it("renders notes text", () => {
    const ind = {
      notes: "Lugn och fin kanin.",
      death_note: null,
    } as Individual;
    renderWithTheme(
      <NotesSection
        individual={ind}
        isEditing={false}
        formData={{}}
        onFieldChange={() => {}}
      />,
    );
    expect(screen.getByText("Lugn och fin kanin.")).toBeDefined();
  });

  it("renders death note when present", () => {
    const ind = {
      notes: null,
      death_note: "2024, vild räv",
    } as Individual;
    renderWithTheme(
      <NotesSection
        individual={ind}
        isEditing={false}
        formData={{}}
        onFieldChange={() => {}}
      />,
    );
    expect(screen.getByText("2024, vild räv")).toBeDefined();
  });

  it("shows empty state when no notes", () => {
    const ind = { notes: null, death_note: null } as Individual;
    renderWithTheme(
      <NotesSection
        individual={ind}
        isEditing={false}
        formData={{}}
        onFieldChange={() => {}}
      />,
    );
    expect(screen.getByText(/Inga anteckningar/)).toBeDefined();
  });
});
