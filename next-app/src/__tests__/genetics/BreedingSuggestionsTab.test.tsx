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

const theme = createTheme();

function renderTab(expectedOffspringF: number | null | undefined) {
  metricsQuery.mockReturnValue({
    data:
      expectedOffspringF === undefined
        ? undefined
        : { expected_offspring_f: expectedOffspringF },
  });
  // Empty result once a query has been made (skipToken before "Beräkna")
  suggestionsQuery.mockImplementation((params: unknown) =>
    typeof params === "object"
      ? { data: [], isLoading: false, isFetching: false, error: undefined }
      : { data: undefined, isLoading: false, isFetching: false },
  );
  return render(
    <ThemeProvider theme={theme}>
      <BreedingSuggestionsTab genebankId={1} />
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
