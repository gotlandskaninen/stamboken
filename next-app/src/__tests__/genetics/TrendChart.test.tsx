import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  within,
} from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { stambokenTheme } from "@/theme/stamboken";

const trendsQuery = vi.fn();

vi.mock("@/redux/api/apiSlice", () => ({
  useFetchGeneticsTrendsQuery: () => trendsQuery(),
}));

// The chart itself is ApexCharts; the stub keeps the props the component hands it.
type ChartProps = {
  options: {
    yaxis: { labels: { formatter: (v: number) => string } };
    tooltip: {
      y: {
        formatter: (
          v: number | null,
          opts?: { dataPointIndex: number },
        ) => string;
      };
    };
    markers: { discrete: { dataPointIndex: number }[] };
    annotations: { xaxis: unknown[] };
  };
  series: { name: string; data: (number | null)[] }[];
};
let chart: ChartProps | undefined;
vi.mock("next/dynamic", () => ({
  default: () => (props: ChartProps) => {
    chart = props;
    return <div data-testid="chart" />;
  },
}));

import TrendChart from "@/components/genetics/TrendChart";

const NBSP = "\u00a0";

const year = (y: number, ne: number | null, n: number | null = 40) => ({
  year: y,
  snapshot_date: `${y + 1}-04-01`,
  population_size: 300,
  active_count: 200,
  mean_inbreeding: 0.0251,
  mean_kinship: 0.0302,
  effective_population_size: ne,
  ne_se: ne == null ? null : 4.4,
  ne_n: n,
  founder_equivalents: 21.74,
  data_quality: "high",
});

function renderChart(rows: object[]) {
  chart = undefined;
  trendsQuery.mockReturnValue({
    data: rows,
    isLoading: false,
    refetch: vi.fn(),
  });
  return render(
    <ThemeProvider theme={stambokenTheme}>
      <TrendChart genebankId={1} />
    </ThemeProvider>,
  );
}

describe("TrendChart", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("draws one metric at a time with Swedish formats", () => {
    renderChart([year(2024, 71.04), year(2025, 70.66)]);
    expect(chart?.series).toEqual([{ name: "Ne", data: [71.04, 70.66] }]);
    expect(chart?.options.yaxis.labels.formatter(70.66)).toBe("71");
    // Never undefined: an update with annotations undefined drops the axes in ApexCharts.
    expect(chart?.options.annotations).toEqual({ xaxis: [] });

    fireEvent.click(
      screen.getByRole("button", { name: "Medelsläktskap (MK)" }),
    );
    expect(chart?.series).toHaveLength(1);
    expect(chart?.series[0].name).toBe("Medelsläktskap (MK)");
    expect(chart?.options.yaxis.labels.formatter(0.0302)).toBe(`3,0${NBSP}%`);
    expect(chart?.options.tooltip.y.formatter(null)).toBe("–");

    fireEvent.click(screen.getByRole("button", { name: "FE" }));
    expect(chart?.series).toEqual([{ name: "FE", data: [21.74, 21.74] }]);
    expect(chart?.options.yaxis.labels.formatter(21.74)).toBe("21,7");
  });

  it("shows Ne with its uncertainty and marks years from few rabbits hollow", () => {
    renderChart([year(2015, 15.2, 12), year(2016, 14.3, 29), year(2017, 30.6)]);
    const { tooltip, markers } = chart!.options;
    expect(tooltip.y.formatter(15.2, { dataPointIndex: 0 })).toBe(
      "15 ± 4, 12 kaniner",
    );
    expect(markers.discrete.map((m) => m.dataPointIndex)).toEqual([0, 1]);
    expect(
      screen.getByText("Ihålig punkt: osäker skattning, färre än 30 kaniner."),
    ).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "FE" }));
    expect(chart!.options.markers.discrete).toEqual([]);
    expect(screen.queryByText(/Ihålig punkt/)).toBeNull();
  });

  it("leaves out an older API's rolling Ne (rows without ne_n)", () => {
    const mainShaped = (y: number) => {
      const { ne_se: _se, ne_n: _n, ...row } = year(y, 449);
      return row;
    };
    renderChart([mainShaped(2024), mainShaped(2025)]);
    expect(screen.queryByRole("button", { name: "Ne" })).toBeNull();
    expect(chart?.series).toEqual([{ name: "FE", data: [21.74, 21.74] }]);
    expect(screen.queryByText(/449/)).toBeNull();
  });

  it("says the values are on their way when no year has been recomputed", () => {
    renderChart([year(2024, null, null), year(2025, null, null)]);
    expect(screen.queryByTestId("chart")).toBeNull();
    expect(screen.getByText(/ladda om sidan om en stund/)).toBeDefined();
    expect(screen.queryByText(/kan inte skattas/)).toBeNull();
  });

  it("names the cause when recomputed years have no estimable Ne", () => {
    for (const [ns, text] of [
      [
        [0, 0],
        "Ne kan inte skattas för de här åren: för få kaniner med känd stamtavla i de här åren.",
      ],
      [
        [12, 40],
        "Inaveln har inte ökat de här åren, så Ne går inte att skatta.",
      ],
      [
        [0, 40],
        "Ne går inte att skatta för de här åren: vissa år har för få kaniner med känd stamtavla, och andra år har inaveln inte ökat.",
      ],
    ] as const) {
      renderChart([year(2024, null, ns[0]), year(2025, null, ns[1])]);
      expect(screen.queryByTestId("chart")).toBeNull();
      expect(screen.getByText(text)).toBeDefined();
      expect(screen.queryByText(/ladda om/)).toBeNull();
      cleanup();
    }
  });

  it("shows one closed year in the table, without a line", () => {
    renderChart([year(2025, 70.66, 315)]);
    expect(screen.queryByTestId("chart")).toBeNull();
    expect(
      screen.getByText(/Diagrammet visas när det finns två stängda år/),
    ).toBeDefined();
    const toggle = screen.getByRole("button", { name: "Visa som tabell" });
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const cells = within(screen.getByRole("table"))
      .getAllByRole("row")
      .slice(1)
      .map((r) =>
        within(r)
          .getAllByRole("cell")
          .map((c) => c.textContent),
      );
    expect(cells).toEqual([["2025", "71", "4", "315"]]);
  });

  it("offers the values as a table, Ne with ± and the number of rabbits", () => {
    renderChart([year(2015, 15.2, 12), year(2016, null, 0), year(2017, 30.6)]);
    const toggle = screen.getByRole("button", { name: "Visa som tabell" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    const table = screen.getByRole("table");
    const head = within(table).getAllByRole("columnheader");
    expect(head.map((h) => h.textContent)).toEqual([
      "År",
      "Ne",
      "Osäkerhet (±)",
      "Antal kaniner",
    ]);
    const cells = within(table)
      .getAllByRole("row")
      .slice(1)
      .map((r) =>
        within(r)
          .getAllByRole("cell")
          .map((c) => c.textContent),
      );
    expect(cells).toEqual([
      ["2015", "15", "4", "12"],
      ["2016", "–", "–", "0"],
      ["2017", "31", "4", "40"],
    ]);

    fireEvent.click(
      screen.getByRole("button", { name: "Medelsläktskap (MK)" }),
    );
    expect(
      within(screen.getByRole("table"))
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["År", "Medelsläktskap (MK)"]);
    // getAllByText compares with the no-break space collapsed.
    expect(screen.getAllByText("3,0 %").length).toBe(3);
  });

  it("explains single years without Ne instead of hiding the chart", () => {
    renderChart([year(2015, null), year(2016, 14.3), year(2017, 17.9)]);
    expect(screen.getByTestId("chart")).toBeDefined();
    expect(screen.getByText(/Ne saknas för år där/)).toBeDefined();
    expect(screen.queryByText(/ladda om sidan/)).toBeNull();
  });
});
