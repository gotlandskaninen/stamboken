import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { BreedingList } from "@/components/herd/BreedingList";

const theme = createTheme();

// Mock the i18n module
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const translations: Record<string, string> = {
        "breeding.noBreedings":
          "Inga kullar eller parningar registrerade ännu.",
        "breeding.litterSize": "födda",
        "breeding.aliveAt6wShort": "vid 6v",
        "breeding.born": "Född",
        "breeding.mating": "Parning",
        "breeding.details": "Detaljer",
      };
      return translations[key] || key;
    },
  }),
}));

const mockBreedings = [
  {
    id: 1,
    mother: "G1274-2041",
    mother_name: "Emma",
    father: "G1158-1624",
    father_name: "Eric",
    birth_date: "2026-03-15",
    breed_date: "2026-02-12",
    litter_size: 6,
    litter_size6w: 5,
    birth_notes: "",
    breed_notes: "",
  },
  {
    id: 2,
    mother: "G1274-2042",
    mother_name: "Charlie",
    father: "G1310-1814",
    father_name: "Asceron",
    birth_date: "2023-05-06",
    breed_date: "2023-04-05",
    litter_size: 9,
    litter_size6w: 4,
    birth_notes: "Stor kull",
    breed_notes: "",
  },
  {
    id: 3,
    mother: "G1115-1971",
    mother_name: "Gryningsvinda",
    father: "G1310-1814",
    father_name: "Asceron",
    birth_date: null,
    breed_date: "2024-04-10",
    litter_size: null,
    litter_size6w: null,
    birth_notes: null,
    breed_notes: "Planerad parning",
  },
];

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

afterEach(cleanup);

describe("BreedingList", () => {
  it("renders breeding entries with parent names", () => {
    renderWithTheme(
      <BreedingList breedings={mockBreedings} isLoading={false} />,
    );

    // Mother × Father names should be visible
    expect(screen.getByText(/Emma/)).toBeDefined();
    expect(screen.getByText(/Eric/)).toBeDefined();
    expect(screen.getByText(/Charlie/)).toBeDefined();
    // Asceron appears in two breedings (id 2 and 3)
    expect(screen.getAllByText(/Asceron/).length).toBe(2);
    expect(screen.getByText(/Gryningsvinda/)).toBeDefined();
  });

  it("renders Okänd instead of a link for a litter without parents", () => {
    const orphan = [
      {
        ...mockBreedings[0],
        mother: null,
        mother_name: null,
        father: null,
        father_name: null,
      },
    ];
    const { container } = renderWithTheme(
      <BreedingList breedings={orphan} isLoading={false} />,
    );
    expect(screen.getAllByText("Okänd").length).toBe(2);
    expect(container.querySelector('a[href$="/individ/null"]')).toBeNull();
  });

  it("shows year group headers", () => {
    renderWithTheme(
      <BreedingList breedings={mockBreedings} isLoading={false} />,
    );

    // Litters group by birth year; the 2024 mating has no birth date yet and
    // therefore renders in the leading "Pågående parningar" section instead of
    // a 2024 year group (handoff README).
    expect(screen.getByText("2026")).toBeDefined();
    expect(screen.getByText("2023")).toBeDefined();
    expect(screen.getByText("Pågående parningar")).toBeDefined();
    expect(screen.queryByText("2024")).toBeNull();
  });

  it("shows empty state when no breedings", () => {
    renderWithTheme(<BreedingList breedings={[]} isLoading={false} />);

    expect(
      screen.getByText("Inga kullar eller parningar registrerade ännu."),
    ).toBeDefined();
  });

  it("shows loading spinner when isLoading", () => {
    renderWithTheme(<BreedingList breedings={[]} isLoading={true} />);

    expect(screen.getByRole("progressbar")).toBeDefined();
  });

  it("shows litter size chip for entries with litter_size", () => {
    renderWithTheme(
      <BreedingList breedings={mockBreedings} isLoading={false} />,
    );

    // First breeding: 6 födda, 5 vid 6v
    expect(screen.getByText("6 födda, 5 vid 6v")).toBeDefined();
    // Second breeding: 9 födda, 4 vid 6v
    expect(screen.getByText("9 födda, 4 vid 6v")).toBeDefined();
  });

  it("expands card on click to show details", () => {
    renderWithTheme(
      <BreedingList breedings={mockBreedings} isLoading={false} />,
    );

    // The second breeding has birth_notes "Stor kull"
    // Before clicking, the note should not be visible (collapsed)
    // Click on the second breeding card to expand it
    const charlieText = screen.getByText(/Charlie/);
    const card = charlieText.closest('[data-testid="breeding-card"]');
    expect(card).not.toBeNull();
    fireEvent.click(card!);

    // After expanding, "Stor kull" should be visible
    expect(screen.getByText("Stor kull")).toBeDefined();
  });
});
