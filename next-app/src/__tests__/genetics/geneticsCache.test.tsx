import React from "react";
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, cleanup, act, waitFor } from "@testing-library/react";
import { Provider } from "react-redux";
import { configureStore } from "@reduxjs/toolkit";
import { ThemeProvider, createTheme } from "@mui/material/styles";

import { apiSlice } from "@/redux/api/apiSlice";
import PrioritiesTab from "@/components/genetics/PrioritiesTab";
import { ModeProvider } from "@/lib/mode-context";
import { MODE_COOKIE, type Mode } from "@/lib/mode";

// The genetics cache with a real RTK store: what an hour-long cache may show.

const theme = createTheme();
const rows = () => screen.queryByText("Kritisk (1)");
const failedAlert = () =>
  screen.queryByText(/Kunde inte hämta prioriteringsdata/);

const priorities = () =>
  new Response(
    JSON.stringify({
      status: "success",
      data: [
        {
          individual_id: "G1-1",
          priority: "critical",
          reasons: [],
          genetic_value_score: 1,
          genome_uniqueness: 0.5,
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

function tab(genebankId: number, mode: Mode) {
  return (
    <Provider store={store}>
      <ThemeProvider theme={theme}>
        <ModeProvider mode={mode}>
          <PrioritiesTab genebankId={genebankId} />
        </ModeProvider>
      </ThemeProvider>
    </Provider>
  );
}

const setModeCookie = (mode: Mode) => {
  document.cookie = `${MODE_COOKIE}=${mode}; path=/`;
};

/** Another request for the same entry, as a second tab or a revisit would make. */
async function refetch(genebankId: number, mode: Mode) {
  await act(async () => {
    const request = store.dispatch(
      apiSlice.endpoints.fetchGeneticPriorities.initiate(
        { genebankId, mode },
        { forceRefetch: true },
      ),
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
      .mockResolvedValue(failure(500));
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
    fetchMock.mockResolvedValue(failure(500));
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
});
