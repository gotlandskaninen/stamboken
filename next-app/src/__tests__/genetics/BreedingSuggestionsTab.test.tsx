import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const metricsQuery = vi.fn();
const suggestionsQuery = vi.fn();

vi.mock("@/redux/api/apiSlice", () => ({
  useFetchPopulationMetricsQuery: (...args: unknown[]) => metricsQuery(...args),
  useFetchBreedingSuggestionsQuery: (...args: unknown[]) =>
    suggestionsQuery(...args),
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
      ? { data: [], isLoading: false, isFetching: false, error: undefined }
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
    );
    expect(
      screen.getByText(
        "Inga par klarar taket 9.0 %. Förväntad inavel vid slumpparning i rasen är 9.0 %. Höj taket för att få förslag.",
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
        "Inga par hittades under taket 6.3 %. Höj taket för att få förslag.",
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
        "Inga par klarar taket 25.0 %. Förväntad inavel vid slumpparning i rasen är 30.0 %.",
      ),
    ).toBeTruthy();
  });
});
