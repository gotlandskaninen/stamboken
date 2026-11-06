import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import { IndividualCard } from "@/components/herd/IndividualCard";
import type { Individual } from "@/redux/api/apiSlice";

const theme = createTheme();

function renderWithTheme(ui: React.ReactElement) {
  return render(<ThemeProvider theme={theme}>{ui}</ThemeProvider>);
}

const mockIndividual: Individual = {
  id: 1,
  number: "G1274-2301",
  name: "Svansen",
  sex: "female",
  herd: { herd: "G1274", herd_name: "Lundbergs", id: 1 },
  genebank_id: 1,
  certificate: null,
  digital_certificate: "D-1234",
  birth_date: "2023-03-15",
  mother: { number: "G1112-1901", name: "Mamma", sex: "female" },
  father: { number: "G1001-1801", name: "Pappa", sex: "male" },
  color: "Svart",
  color_note: null,
  death_date: null,
  death_note: null,
  selling_date: null,
  litter_size: 6,
  litter_size6w: 5,
  notes: null,
  herd_tracking: [],
  herd_active: true,
  is_active: true,
  is_registered: true,
  has_photo: false,
  alive: true,
  belly_color: null,
  eye_color: null,
  claw_color: null,
  hair_notes: "",
  breeding: 1,
  butchered: false,
  castration_date: null,
};

afterEach(cleanup);

describe("IndividualCard", () => {
  it("renders individual number and name", () => {
    renderWithTheme(<IndividualCard individual={mockIndividual} />);
    expect(screen.getByText("G1274-2301")).toBeDefined();
    expect(screen.getByText("Svansen")).toBeDefined();
  });

  it("renders sex badge", () => {
    renderWithTheme(<IndividualCard individual={mockIndividual} />);
    expect(screen.getAllByText("Hona").length).toBeGreaterThan(0);
  });

  it("renders status badge for active rabbit", () => {
    renderWithTheme(<IndividualCard individual={mockIndividual} />);
    expect(screen.getAllByText("Aktiv").length).toBeGreaterThan(0);
  });

  it("shows actions when provided", () => {
    renderWithTheme(
      <IndividualCard
        individual={mockIndividual}
        actions={<button>Redigera</button>}
      />,
    );
    expect(screen.getAllByText("Redigera").length).toBeGreaterThan(0);
  });

  it("hides actions when not provided", () => {
    renderWithTheme(<IndividualCard individual={mockIndividual} />);
    expect(screen.queryByText("Redigera")).toBeNull();
  });

  it("renders the genetics slot", () => {
    renderWithTheme(
      <IndividualCard
        individual={mockIndividual}
        geneticsSlot={<p>genetik-slot</p>}
      />,
    );
    expect(screen.getByText("genetik-slot")).toBeDefined();
  });

  it("shows deceased status when death_date is set", () => {
    const deadRabbit = {
      ...mockIndividual,
      death_date: "2024-01-15",
      alive: false,
      is_active: false,
    };
    renderWithTheme(<IndividualCard individual={deadRabbit} />);
    expect(screen.getByText("Död")).toBeDefined();
  });

  it("dates Köpt from the latest TRANSFER row, not the latest yearly report", () => {
    const bought = {
      ...mockIndividual,
      origin_herd: { herd: "G1001", herd_name: "Annan", id: 2 },
      herd_tracking: [
        {
          herd_id: 1,
          herd: "G1274",
          herd_name: null,
          date: "2025-01-15",
          kind: "ATTESTATION" as const,
        },
        {
          herd_id: 1,
          herd: "G1274",
          herd_name: null,
          date: "2024-03-01",
          kind: "TRANSFER" as const,
        },
        {
          herd_id: 2,
          herd: "G1001",
          herd_name: null,
          date: "2023-03-15",
          kind: "BIRTH" as const,
        },
      ],
    };
    renderWithTheme(<IndividualCard individual={bought} />);
    expect(screen.getByLabelText("Köpt 2024-03-01 från G1001")).toBeDefined();
  });
});
