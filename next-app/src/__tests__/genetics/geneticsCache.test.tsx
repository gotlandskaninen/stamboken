import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  act,
  waitFor,
  fireEvent,
} from "@testing-library/react";
import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import { ThemeProvider, createTheme } from "@mui/material/styles";

// Read when apiSlice loads: demo requests go to /api-test, as in production.
vi.hoisted(() => {
  process.env.NEXT_PUBLIC_API_TEST_URL = "/api-test";
});

import { apiSlice } from "@/redux/api/apiSlice";
import FoundersAtRiskPanel from "@/components/genetics/FoundersAtRiskPanel";
import BreedingSuggestionsTab from "@/components/genetics/BreedingSuggestionsTab";
import { ModeProvider } from "@/lib/mode-context";
import { MODE_COOKIE, type Mode } from "@/lib/mode";

// The genetics cache with a real RTK store: what an hour-long cache may show. Shown on the
// founderdjur table: the Avelsprioritet list reads the logged work list instead (useWorkList).

const theme = createTheme();
const rows = () => screen.queryByText("Founderdjurens läge (1 founderdjur)");
const failedAlert = () =>
  screen.queryByText(/inte behörighet|gick inte att hämta/);

const priorities = () =>
  new Response(
    JSON.stringify({
      status: "success",
      data: [
        {
          founder_id: "G1-1",
          risk_level: "critical",
          n_carriers: 1,
          avg_contribution: 0.1,
          allele_retention: null,
          carrier_ids: ["G1-2"],
          recoverable_carriers: [],
        },
      ],
    }),
    { status: 200, headers: { "content-type": "application/json" } },
  );
const failure = (status: number) =>
  new Response(JSON.stringify({ status: "error" }), {
    status,
    headers: { "content-type": "application/json" },
  });

let fetchMock: ReturnType<typeof vi.fn>;
let store: ReturnType<typeof makeStore>;

function makeStore() {
  return configureStore({
    reducer: { [apiSlice.reducerPath]: apiSlice.reducer },
    middleware: (getDefault) => getDefault().concat(apiSlice.middleware),
    // Notify at once, not on the next animation frame: each step's answer renders inside act().
    enhancers: (getDefault) => getDefault({ autoBatch: false }),
  });
}

function tab(
  genebankId: number,
  mode: Mode,
  Panel: React.ComponentType<{ genebankId: number }> = FoundersAtRiskPanel,
) {
  return (
    <Provider store={store}>
      <ThemeProvider theme={theme}>
        <ModeProvider mode={mode}>
          <Panel genebankId={genebankId} />
        </ModeProvider>
      </ThemeProvider>
    </Provider>
  );
}

const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });

/** Answer each request by the first handler whose path part its URL contains. */
const route = (handlers: Record<string, () => Response>) =>
  fetchMock.mockImplementation(async (request: { url: string }) => {
    const hit = Object.keys(handlers).find((part) =>
      request.url.includes(part),
    );
    return hit ? handlers[hit]() : failure(404);
  });

const requested = (part: string) =>
  fetchMock.mock.calls
    .map(([request]) => (request as { url: string }).url)
    .filter((url) => url.includes(part));

const setModeCookie = (mode: Mode) => {
  document.cookie = `${MODE_COOKIE}=${mode}; path=/`;
};

/** Another request for the same entry, as a second tab or a revisit would make. */
async function refetch(
  genebankId: number,
  mode: Mode,
  endpoint:
    | "fetchFoundersAtRisk"
    | "fetchPopulationMetrics" = "fetchFoundersAtRisk",
) {
  const arg = { genebankId, mode };
  const options = { forceRefetch: true };
  await act(async () => {
    const request =
      endpoint === "fetchPopulationMetrics"
        ? store.dispatch(
            apiSlice.endpoints.fetchPopulationMetrics.initiate(arg, options),
          )
        : store.dispatch(
            apiSlice.endpoints.fetchFoundersAtRisk.initiate(arg, options),
          );
    await request;
    request.unsubscribe();
  });
}

describe("genetics cache", () => {
  beforeEach(() => {
    store = makeStore();
    fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    // fetchBaseQuery's timeout builds an AbortController whose signal undici's
    // Request rejects under jsdom (see apiSlice.test.ts).
    class CapturingRequest {
      url: string;
      constructor(input: string | { url: string }) {
        this.url = typeof input === "string" ? input : input.url;
      }
    }
    vi.stubGlobal("Request", CapturingRequest);
    setModeCookie("prod");
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    document.cookie = `${MODE_COOKIE}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });

  it("keeps rows a 403 disowned hidden when the next refetch fails otherwise", async () => {
    fetchMock.mockResolvedValueOnce(priorities());
    render(tab(11, "prod"));
    await waitFor(() => expect(rows()).toBeTruthy());

    fetchMock.mockResolvedValueOnce(failure(403));
    await refetch(11, "prod");
    expect(rows()).toBeNull();
    expect(failedAlert()).toBeTruthy();

    fetchMock.mockResolvedValueOnce(failure(500));
    await refetch(11, "prod");
    expect(rows()).toBeNull();
    expect(failedAlert()).toBeTruthy();

    fetchMock.mockResolvedValueOnce(priorities()); // access confirmed again
    await refetch(11, "prod");
    expect(rows()).toBeTruthy();
  });

  it("keeps them hidden from a tab that mounts after the 403 was answered elsewhere", async () => {
    fetchMock
      .mockResolvedValueOnce(priorities())
      .mockResolvedValueOnce(failure(403))
      .mockResolvedValueOnce(failure(500))
      .mockImplementation(async () => failure(500));
    await refetch(12, "prod");
    await refetch(12, "prod");
    await refetch(12, "prod");

    render(tab(12, "prod")); // sees only the 500 and the old data
    expect(rows()).toBeNull();
    await waitFor(() => expect(failedAlert()).toBeTruthy());
    expect(rows()).toBeNull();
  });

  it("never shows demo rows after a switch to production", async () => {
    setModeCookie("demo");
    fetchMock.mockResolvedValueOnce(priorities());
    const { rerender, unmount } = render(tab(13, "demo"));
    await waitFor(() => expect(rows()).toBeTruthy());

    // The tab stays mounted through the switch; production fails.
    setModeCookie("prod");
    fetchMock.mockImplementation(async () => failure(500));
    rerender(tab(13, "prod"));
    expect(rows()).toBeNull();
    await waitFor(() => expect(failedAlert()).toBeTruthy());
    expect(rows()).toBeNull();

    // A revisit after the switch: still no demo rows.
    unmount();
    render(tab(13, "prod"));
    await waitFor(() => expect(failedAlert()).toBeTruthy());
    expect(rows()).toBeNull();
  });

  it("sends each request to the backend its cache key names, whatever the cookie says", async () => {
    // Another browser tab switched the cookie since this page rendered.
    setModeCookie("demo");
    fetchMock.mockImplementation(async () => priorities());
    render(tab(14, "prod"));
    await waitFor(() => expect(rows()).toBeTruthy());
    cleanup();
    setModeCookie("prod");
    render(tab(15, "demo"));
    await waitFor(() => expect(rows()).toBeTruthy());

    expect(requested("founders-at-risk")).toEqual([
      "/api/14/founders-at-risk/",
      "/api-test/15/founders-at-risk/",
    ]);
  });

  it("hides every panel of a genebank after a 403 from any of its genetics endpoints", async () => {
    fetchMock.mockResolvedValueOnce(priorities());
    render(tab(16, "prod"));
    await waitFor(() => expect(rows()).toBeTruthy());

    fetchMock.mockResolvedValueOnce(failure(403));
    await refetch(16, "prod", "fetchPopulationMetrics"); // the overview's query
    expect(rows()).toBeNull();
    expect(failedAlert()).toBeTruthy();

    fetchMock.mockResolvedValueOnce(failure(500));
    await refetch(16, "prod"); // priorities fail otherwise: still nothing from before
    expect(rows()).toBeNull();

    fetchMock.mockResolvedValueOnce(priorities());
    await refetch(16, "prod");
    expect(rows()).toBeTruthy();
  });

  it("drops the other mode's pairs at a switch and asks again with the same parameters", async () => {
    const pairs = (sire: string) => () =>
      json({
        status: "success",
        data: [
          {
            sire_id: sire,
            dam_id: "D-1",
            expected_f: 0.01,
            delta_gd: 0.001,
            mate_suitability_index: 1,
            reasons: [],
          },
        ],
      });
    const metrics = () => json({ expected_offspring_f: 0.03 });
    setModeCookie("demo");
    route({
      "population-metrics": metrics,
      "breeding-suggestions": pairs("S-DEMO"),
    });
    const { rerender } = render(tab(17, "demo", BreedingSuggestionsTab));
    const calculate = () =>
      screen.getByRole("button", { name: "Beräkna" }) as HTMLButtonElement;
    await waitFor(() => expect(calculate().disabled).toBe(false));
    fireEvent.click(calculate());
    await waitFor(() => expect(screen.queryByText("S-DEMO")).toBeTruthy());

    // The admin panel's "Byt till produktion": the panel stays mounted.
    setModeCookie("prod");
    route({
      "population-metrics": metrics,
      "breeding-suggestions": pairs("S-PROD"),
    });
    rerender(tab(17, "prod", BreedingSuggestionsTab));
    expect(screen.queryByText("S-DEMO")).toBeNull();
    await waitFor(() => expect(calculate().disabled).toBe(false));
    fireEvent.click(calculate()); // the same parameters
    await waitFor(() => expect(screen.queryByText("S-PROD")).toBeTruthy());
    expect(screen.queryByText("S-DEMO")).toBeNull();
    expect(
      requested("breeding-suggestions").map((url) => url.split("/")[1]),
    ).toEqual(["api-test", "api"]);
  });

  it("hides rows asked for before a 403 that answer after it", async () => {
    let answer: ((response: Response) => void) | undefined;
    fetchMock.mockImplementationOnce(
      () => new Promise<Response>((resolve) => (answer = resolve)),
    );
    render(tab(41, "prod")); // request A starts
    await waitFor(() => expect(answer).toBeDefined());

    fetchMock.mockResolvedValueOnce(failure(403));
    await refetch(41, "prod", "fetchPopulationMetrics"); // revoked meanwhile
    await act(async () => answer?.(priorities())); // A ends with a 200
    expect(rows()).toBeNull();
    expect(failedAlert()).toBeTruthy();

    fetchMock.mockResolvedValueOnce(failure(500));
    await refetch(41, "prod");
    expect(rows()).toBeNull();

    await new Promise((resolve) => setTimeout(resolve, 5)); // a later millisecond
    fetchMock.mockResolvedValueOnce(priorities());
    await refetch(41, "prod"); // asked for after the 403
    expect(rows()).toBeTruthy();
  });

  it("asks the server again at each Beräkna once access is restored", async () => {
    route({
      "population-metrics": () => json({ expected_offspring_f: 0.03 }),
      "breeding-suggestions": () =>
        json({
          status: "success",
          data: [
            {
              sire_id: "S-1",
              dam_id: "D-1",
              expected_f: 0.01,
              delta_gd: 0.001,
              mate_suitability_index: 1,
              reasons: [],
            },
          ],
        }),
    });
    render(tab(42, "prod", BreedingSuggestionsTab));
    const calculate = () =>
      screen.getByRole("button", { name: "Beräkna" }) as HTMLButtonElement;
    const pairsShown = () => screen.queryByText("S-1");
    await waitFor(() => expect(calculate().disabled).toBe(false));
    fireEvent.click(calculate());
    await waitFor(() => expect(pairsShown()).toBeTruthy());

    fetchMock.mockResolvedValueOnce(failure(403));
    await refetch(42, "prod"); // the priorities tab is denied
    expect(pairsShown()).toBeNull();
    expect(screen.getByText(/inte behörighet/)).toBeTruthy();

    await new Promise((resolve) => setTimeout(resolve, 5)); // access restored later
    for (const asked of [2, 3]) {
      await waitFor(() => expect(calculate().disabled).toBe(false));
      fireEvent.click(calculate()); // the same parameters
      await waitFor(() =>
        expect(requested("breeding-suggestions")).toHaveLength(asked),
      );
      await waitFor(() => expect(pairsShown()).toBeTruthy());
    }
  });
});
