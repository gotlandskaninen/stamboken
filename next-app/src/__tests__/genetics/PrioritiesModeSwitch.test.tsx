import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  act,
  waitFor,
  fireEvent,
} from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

const modes = vi.hoisted(() => ({ view: "prod" }));
vi.mock("@/lib/mode-context", () => ({ useMode: () => modes.view }));
// jsdom has no layout, so the real grid renders no cells: list the rabbits' numbers instead.
vi.mock("@mui/x-data-grid", () => ({
  DataGrid: ({ rows }: { rows: { individual_id: string }[] }) => (
    <ul>
      {rows.map((r) => (
        <li key={r.individual_id}>{r.individual_id}</li>
      ))}
    </ul>
  ),
}));

import PrioritiesTab from "@/components/genetics/PrioritiesTab";

const rabbit = (individual_id: string) => ({
  individual_id,
  priority: "critical",
  reasons: [],
  genetic_value_score: 90,
  genome_uniqueness: 0.1,
});

describe("Avelsprioritet after a mode switch", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    modes.view = "prod";
  });

  const tab = () => (
    <ThemeProvider theme={createTheme()}>
      <PrioritiesTab genebankId={1} />
    </ThemeProvider>
  );

  it("never saves a file that was still on its way when the mode switched", async () => {
    let answerFile: () => void = () => {};
    vi.stubEnv("NEXT_PUBLIC_API_TEST_URL", "/api-test");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string, init: RequestInit) => {
        if (url.includes("priorities.csv"))
          return new Promise<Response>((resolve, reject) => {
            init.signal?.addEventListener("abort", () =>
              reject(new DOMException("aborted", "AbortError")),
            );
            answerFile = () => resolve(new Response("x"));
          });
        return url.startsWith("/api-test")
          ? new Promise<Response>(() => {})
          : Promise.resolve(Response.json([rabbit("G1-2301")]));
      }),
    );
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click");
    const { rerender } = render(tab());
    expect(await screen.findByText("G1-2301")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Ladda ner CSV" }));
    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        expect.stringContaining("priorities.csv"),
        expect.anything(),
      ),
    );

    modes.view = "demo";
    rerender(tab());
    await act(async () => answerFile());
    expect(click).not.toHaveBeenCalled();
  });

  it("shows neither the other mode's rows nor a CSV button for them while its own list loads", async () => {
    let answerDemo: (r: Response) => void = () => {};
    vi.stubEnv("NEXT_PUBLIC_API_TEST_URL", "/api-test");
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.startsWith("/api-test")
          ? new Promise<Response>((resolve) => (answerDemo = resolve))
          : Promise.resolve(Response.json([rabbit("G1-2301")])),
      ),
    );
    const { rerender } = render(tab());
    expect(await screen.findByText("G1-2301")).toBeDefined();

    modes.view = "demo"; // the mode toggle re-renders the page in the testmiljö
    rerender(tab());
    expect(screen.queryByText("G1-2301")).toBeNull();
    expect(screen.queryByRole("button", { name: "Ladda ner CSV" })).toBeNull();
    expect(screen.getByText(/Beräknar genetiska prioriteringar/)).toBeDefined();

    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    await act(async () => answerDemo(Response.json([rabbit("G1-9901")])));
    expect(await screen.findByText("G1-9901")).toBeDefined();
    expect(screen.queryByText("G1-2301")).toBeNull();
  });
});
