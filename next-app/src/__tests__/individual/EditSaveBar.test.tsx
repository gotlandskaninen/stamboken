import React from "react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { EditSaveBar } from "@/components/individual/EditSaveBar";

const theme = createTheme();

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

afterEach(cleanup);

describe("EditSaveBar", () => {
  it("is not visible when not dirty", () => {
    renderWithTheme(
      <EditSaveBar
        isDirty={false}
        isSaving={false}
        onSave={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.queryByText("Spara")).toBeNull();
  });

  it("shows save and cancel buttons when dirty", () => {
    renderWithTheme(
      <EditSaveBar
        isDirty={true}
        isSaving={false}
        onSave={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText("Spara")).toBeDefined();
    expect(screen.getByText("Avbryt")).toBeDefined();
  });

  it("calls onSave when save is clicked", () => {
    const onSave = vi.fn();
    renderWithTheme(
      <EditSaveBar
        isDirty={true}
        isSaving={false}
        onSave={onSave}
        onCancel={() => {}}
      />,
    );
    fireEvent.click(screen.getByText("Spara"));
    expect(onSave).toHaveBeenCalledOnce();
  });

  it("disables save button when saving", () => {
    renderWithTheme(
      <EditSaveBar
        isDirty={true}
        isSaving={true}
        onSave={() => {}}
        onCancel={() => {}}
      />,
    );
    expect(screen.getByText("Sparar...")).toBeDefined();
  });
});
