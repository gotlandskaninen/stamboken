import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const prioritiesQuery = vi.fn();

// The list comes from the logged work-list route (useWorkList), not an RTK hook.
vi.mock("@/components/genetics/workList", async (original) => ({
  ...(await original<typeof import("@/components/genetics/workList")>()),
  useWorkList: () => prioritiesQuery(),
}));
vi.mock("@/lib/mode-context", () => ({ useMode: () => "prod" }));

// jsdom has no layout, so the real grid renders no cells. The stub renders each
// cell through the column's valueFormatter with the row, as the grid does.
type Column = {
  field: string;
  valueFormatter?: (value: unknown, row: Record<string, unknown>) => string;
};
vi.mock("@mui/x-data-grid", () => ({
  DataGrid: ({
    rows,
    columns,
  }: {
    rows: Record<string, unknown>[];
    columns: Column[];
  }) => (
    <table>
      <tbody>
        {rows.map((row) => (
          <tr key={String(row.id)}>
            {columns.map((c) => (
              <td key={c.field}>
                {c.valueFormatter
                  ? c.valueFormatter(row[c.field], row)
                  : String(row[c.field])}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  ),
}));

import PrioritiesTab from "@/components/genetics/PrioritiesTab";

const row = (individual_id: string, founder: string) => ({
  individual_id,
  priority: "critical",
  reasons: [
    `Sole active carrier of founder ${founder}`,
    "Mean kinship 0.0023 is below 5th percentile (0.0023)",
  ],
  genetic_value_score: 91.4,
  genome_uniqueness: 0.103,
});

describe("PrioritiesTab", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("translates each row's reasons with that row's own number", () => {
    prioritiesQuery.mockReturnValue({
      data: [row("G1-2050", "G1-2050"), row("G1-2115", "G1-1101")],
      isLoading: false,
      refetch: vi.fn(),
    });
    render(
      <ThemeProvider theme={createTheme()}>
        <PrioritiesTab genebankId={1} />
      </ThemeProvider>,
    );
    expect(
      screen.getByText(
        "Är själv founderdjur och har inga ättlingar i beräkningen; Medelsläktskap 0,23 %, på eller under gränsen för de 5 % minst släkta (0,23 %)",
      ),
    ).toBeDefined();
    expect(
      screen.getByText(
        /^Enda kaninen i beräkningen med gener från founderdjuret G1-1101; /,
      ),
    ).toBeDefined();
    expect(screen.getAllByText("91")).toHaveLength(2);
    expect(screen.getAllByText("10,3 %")).toHaveLength(2);
  });
});
