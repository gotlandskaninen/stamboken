import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const metricsQuery = vi.fn();
const suggestionsQuery = vi.fn();

// The answer is the current argument's own, as RTK Query's currentData after a fetch.
const own = (r: { data?: unknown; isLoading?: boolean }) => ({
  currentData: r.data,
  isFetching: Boolean(r.isLoading),
  ...r,
});

vi.mock("@/redux/api/apiSlice", () => ({
  useFetchPopulationMetricsQuery: (...args: unknown[]) =>
    own(metricsQuery(...args)),
  useFetchBreedingSuggestionsQuery: (...args: unknown[]) =>
    own(suggestionsQuery(...args)),
}));

import BreedingSuggestionsTab from "@/components/genetics/BreedingSuggestionsTab";
import { ModeProvider } from "@/lib/mode-context";

const theme = createTheme();

function renderTab(
  expectedOffspringF: number | null | undefined,
  metricsState: Record<string, unknown> = {},
) {
  const data =
    expectedOffspringF === undefined
      ? undefined
      : { expected_offspring_f: expectedOffspringF };
  metricsQuery.mockReturnValue({
    data,
    currentData: data,
    isFetching: false,
    ...metricsState,
  });
  // Empty result once a query has been made (skipToken before "Beräkna")
  suggestionsQuery.mockImplementation((params: unknown) =>
    typeof params === "object"
      ? {
          data: [],
          currentData: [],
          isLoading: false,
          isFetching: false,
          error: undefined,
        }
      : { data: undefined, isLoading: false, isFetching: false },
  );
  return render(
    <ThemeProvider theme={theme}>
      <ModeProvider mode="prod">
        <BreedingSuggestionsTab genebankId={1} />
      </ModeProvider>
    </ThemeProvider>,
  );
}

const capField = () =>
  screen.getByLabelText("Max inavel (F)") as HTMLInputElement;

describe("BreedingSuggestionsTab", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  it("drops the calculation made in the other mode", () => {
    const { rerender } = renderTab(0.03);
    fireEvent.click(screen.getByRole("button", { name: "Beräkna" }));
    expect(suggestionsQuery).toHaveBeenLastCalledWith(
      expect.objectContaining({ genebankId: 1, mode: "prod" }),
      { refetchOnMountOrArgChange: true },
    );
    // The admin panel's switch re-renders the mounted tab in the other mode.
    rerender(
      <ThemeProvider theme={theme}>
        <ModeProvider mode="demo">
          <BreedingSuggestionsTab genebankId={1} />
        </ModeProvider>
      </ThemeProvider>,
    );
    expect(typeof suggestionsQuery.mock.lastCall?.[0]).toBe("symbol"); // skipToken
    expect(screen.getByText(/Klicka "Beräkna"/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Beräkna" }));
    expect(suggestionsQuery).toHaveBeenLastCalledWith(
      expect.objectContaining({ genebankId: 1, mode: "demo" }),
      { refetchOnMountOrArgChange: true },
    );
  });

  it("refreshes the metrics and waits for them before an automatic cap is sent", () => {
    renderTab(0.09, { isFetching: true }); // an hour-old value is cached
    expect(metricsQuery).toHaveBeenCalledWith(
      { genebankId: 1, mode: "prod" },
      { refetchOnMountOrArgChange: true },
    );
    const calculate = screen.getByRole("button", { name: "Beräkna" });
    expect((calculate as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(capField(), { target: { value: "0.1" } }); // a typed cap does not wait
    expect((calculate as HTMLButtonElement).disabled).toBe(false);
  });

  it("treats the expected F as unknown when its refresh failed", () => {
    renderTab(0.09, { error: { status: 500 } });
    expect(capField().value).toBe("0.0625");
  });

  it("defaults the cap to the breed's expected offspring F when it is higher", () => {
    renderTab(0.09);
    expect(capField().value).toBe("0.09");
  });

  it("keeps 0.0625 when the expected offspring F is lower or unknown", () => {
    renderTab(0.03);
    expect(capField().value).toBe("0.0625");
    cleanup();
    renderTab(undefined);
    expect(capField().value).toBe("0.0625");
  });

  it("explains an empty result with the cap and the expected F", () => {
    renderTab(0.09);
    fireEvent.click(screen.getByRole("button", { name: "Beräkna" }));
    expect(suggestionsQuery).toHaveBeenLastCalledWith(
      expect.objectContaining({ genebankId: 1, maxInbreeding: 0.09 }),
      { refetchOnMountOrArgChange: true },
    );
    expect(
      screen.getByText(
        "Inga par klarar taket 9,0 %. Förväntad inavel vid slumpparning i rasen är 9,0 %. Höj taket för att få förslag.",
      ),
    ).toBeTruthy();
  });

  it("rounds the derived default up to 4 decimals", () => {
    renderTab(0.078125);
    expect(capField().value).toBe("0.0782");
    cleanup();
    renderTab(0.125 + 2 ** -45);
    expect(capField().value).toBe("0.1251");
    cleanup();
    renderTab(0.0625);
    expect(capField().value).toBe("0.0625");
  });

  it("stays neutral while the expected F is unknown (loading or failed)", () => {
    renderTab(undefined);
    fireEvent.click(screen.getByRole("button", { name: "Beräkna" }));
    expect(
      screen.getByText(
        "Inga par hittades under taket 6,3 %. Höj taket för att få förslag.",
      ),
    ).toBeTruthy();
  });

  it("says why when the reference population lacks males or females", () => {
    renderTab(null);
    fireEvent.click(screen.getByRole("button", { name: "Beräkna" }));
    expect(
      screen.getByText(
        "Referenspopulationen saknar hanar eller honor, så inga par kan föreslås.",
      ),
    ).toBeTruthy();
  });

  it("does not suggest raising the cap when it is already at the maximum", () => {
    renderTab(0.3);
    expect(capField().value).toBe("0.25");
    fireEvent.click(screen.getByRole("button", { name: "Beräkna" }));
    expect(
      screen.getByText(
        "Inga par klarar taket 25,0 %. Förväntad inavel vid slumpparning i rasen är 30,0 %.",
      ),
    ).toBeTruthy();
  });
});

describe("BreedingSuggestionsTab errors", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  const renderWithError = (error: object) => {
    const refetch = vi.fn();
    metricsQuery.mockReturnValue({ data: { expected_offspring_f: 0.03 } });
    suggestionsQuery.mockImplementation((params: unknown) =>
      typeof params === "object"
        ? {
            data: undefined,
            isLoading: false,
            isFetching: false,
            error,
            refetch,
          }
        : { data: undefined, isLoading: false, isFetching: false, refetch },
    );
    render(
      <ThemeProvider theme={theme}>
        <ModeProvider mode="prod">
          <BreedingSuggestionsTab genebankId={1} />
        </ModeProvider>
      </ThemeProvider>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Beräkna" }));
    return refetch;
  };

  it("names a missing access, not the sexes, for 403", () => {
    renderWithError({ status: 403 });
    expect(screen.getByText(/inte behörighet/)).toBeTruthy();
    expect(screen.queryByText(/könsdata|hanar eller honor/)).toBeNull();
  });

  it("offers a retry for a failed computation", () => {
    const refetch = renderWithError({ status: 500 });
    expect(
      screen.getByText(
        "Beräkningen gick inte att hämta. Försök igen om en stund.",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(refetch).toHaveBeenCalled();
  });

  it("drops the previous answer's pairs when a lower cap is denied", () => {
    const pair = {
      sire_id: "G1-2301",
      dam_id: "G1-2302",
      expected_f: 0.1,
      delta_gd: 0.001,
      mate_suitability_index: 3,
      reasons: [],
    };
    metricsQuery.mockReturnValue({ data: { expected_offspring_f: 0.03 } });
    // RTK Query keeps `data` from the 12 % answer while 5 % loads and after it fails;
    // `currentData` is only ever the answer for the submitted parameters.
    let phase: "loading" | "denied" = "loading";
    suggestionsQuery.mockImplementation((params: unknown) => {
      const cap = (params as { maxInbreeding?: number })?.maxInbreeding;
      if (typeof params !== "object") return { data: undefined };
      if (cap === 0.12) return { data: [pair], currentData: [pair] };
      return phase === "loading"
        ? { data: [pair], currentData: undefined, isFetching: true }
        : {
            data: [pair],
            currentData: undefined,
            error: { status: 403 },
            refetch: vi.fn(),
          };
    });
    const { rerender } = render(
      <ThemeProvider theme={theme}>
        <ModeProvider mode="prod">
          <BreedingSuggestionsTab genebankId={1} />
        </ModeProvider>
      </ThemeProvider>,
    );
    fireEvent.change(capField(), { target: { value: "0.12" } });
    fireEvent.click(screen.getByRole("button", { name: "Beräkna" }));
    expect(screen.getByText("G1-2301")).toBeTruthy();

    fireEvent.change(capField(), { target: { value: "0.05" } });
    fireEvent.click(screen.getByRole("button", { name: "Beräkna" }));
    expect(screen.queryByText("G1-2301")).toBeNull(); // loading the 5 % answer

    phase = "denied";
    rerender(
      <ThemeProvider theme={theme}>
        <ModeProvider mode="prod">
          <BreedingSuggestionsTab genebankId={1} />
        </ModeProvider>
      </ThemeProvider>,
    );
    expect(screen.getByText(/inte behörighet/)).toBeTruthy();
    expect(screen.queryByText("G1-2301")).toBeNull();
    expect(screen.queryByText(/Inga par/)).toBeNull();
  });
});
