import { describe, it, expect, vi, afterEach } from "vitest";

import { renderHook, waitFor, act } from "@testing-library/react";
import {
  EXPORT_ONLY_IN_PROD,
  WorkListRow,
  byHerd,
  downloadExport,
  exportRefusal,
  prioritiesCsvUrl,
  sexLabel,
  useWorkList,
} from "@/components/genetics/workList";

const row = (
  individual_id: string,
  priority: WorkListRow["priority"],
  herd: string,
): WorkListRow => ({
  individual_id,
  priority,
  reasons: [],
  genetic_value_score: 91.4,
  genome_uniqueness: 0.103,
  herd,
});

describe("byHerd", () => {
  it("keeps the levels in order and groups each level's rows per besättning, G9 before G10", () => {
    const sorted = byHerd([
      row("G10-1", "critical", "G10"),
      row("G9-1", "important", "G9"),
      row("G9-2", "critical", "G9"),
      row("G10-2", "critical", "G10"),
    ]);
    expect(sorted.map((r) => r.individual_id)).toEqual([
      "G9-2",
      "G10-1",
      "G10-2",
      "G9-1",
    ]);
  });
});

describe("sexLabel", () => {
  it("names the legacy eunuch value and an unknown sex", () => {
    expect(sexLabel("female")).toBe("Hona");
    expect(sexLabel("male")).toBe("Hane");
    expect(sexLabel("eunuch")).toBe("Hane (kastrerad)");
    expect(sexLabel(null)).toBe("Okänt");
  });
});

describe("prioritiesCsvUrl", () => {
  it("asks the production API for the chosen levels and order", () => {
    expect(prioritiesCsvUrl(1, ["critical", "normal"], true)).toBe(
      "/api/v2/genetics/1/priorities.csv?levels=critical,normal&per_herd=1",
    );
    expect(prioritiesCsvUrl(2, ["critical"], false)).toBe(
      "/api/v2/genetics/2/priorities.csv?levels=critical",
    );
  });
});

describe("exportRefusal", () => {
  it("lets only a production view export, and only while the cookie still says production", () => {
    expect(exportRefusal("prod", "prod")).toBeNull();
    expect(exportRefusal("demo", "demo")).toBe(EXPORT_ONLY_IN_PROD);
    expect(exportRefusal("demo", "prod")).toBe(EXPORT_ONLY_IN_PROD);
    expect(exportRefusal("prod", "demo")).toMatch(/annan flik/);
  });
});

describe("useWorkList", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  const answer = (status: number, body: unknown) =>
    vi.fn(async () => Response.json(body, { status }));

  it("loads the logged work list of the genebank, on the API of the view's mode", async () => {
    const fetchMock = answer(200, [row("G9-1", "critical", "G9")]);
    vi.stubGlobal("fetch", fetchMock);
    vi.stubEnv("NEXT_PUBLIC_API_TEST_URL", "/api-test");
    const { result, rerender } = renderHook(
      ({ mode }: { mode: "prod" | "demo" }) => useWorkList(1, mode),
      { initialProps: { mode: "prod" as "prod" | "demo" } },
    );
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.data).toHaveLength(1));
    expect(result.current.isLoading).toBe(false);
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/v2/genetics/1/work-list",
      expect.objectContaining({ credentials: "include" }),
    );
    rerender({ mode: "demo" });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/api-test/v2/genetics/1/work-list",
        expect.objectContaining({ credentials: "include" }),
      ),
    );
  });

  it("gives the status of a refusal, and loads again on retry", async () => {
    const fetchMock = answer(403, { detail: "nej" });
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useWorkList(2, "prod"));
    await waitFor(() => expect(result.current.error).toEqual({ status: 403 }));
    expect(result.current.data).toBeUndefined();

    fetchMock.mockImplementation(async () => Response.json([]));
    act(() => result.current.refetch());
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.data).toEqual([]));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("never sends a read the page drops at once, as React's dev double mount does", async () => {
    const fetchMock = vi.fn(() => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    renderHook(() => useWorkList(1, "prod")).unmount();
    await new Promise((r) => setTimeout(r, 10));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("aborts a sent read the page no longer needs", async () => {
    const fetchMock = vi.fn(() => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    const { unmount } = renderHook(() => useWorkList(1, "prod"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    unmount();
    const init = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(init[1].signal?.aborted).toBe(true);
  });

  it("names a network failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        throw new TypeError("offline");
      }),
    );
    const { result } = renderHook(() => useWorkList(1, "prod"));
    await waitFor(() =>
      expect(result.current.error).toEqual({ status: "FETCH_ERROR" }),
    );
  });
});

describe("downloadExport", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
  });

  it("returns the server's reason for a refusal and downloads nothing", async () => {
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        Response.json(
          { detail: "Exporten går bara att göra i den riktiga Stamboken." },
          { status: 403 },
        ),
      ),
    );
    expect(await downloadExport("/x.csv")).toBe(
      "Exporten går bara att göra i den riktiga Stamboken.",
    );
    expect(click).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });

  it("saves the file under the server's name and frees it after the click", async () => {
    vi.useFakeTimers();
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, "click")
      .mockImplementation(function (this: HTMLAnchorElement) {
        expect(this.download).toBe("avelsprioritet-genbank-1-2026-11-25.csv");
        expect(document.body.contains(this)).toBe(true);
      });
    URL.createObjectURL = vi.fn(() => "blob:x");
    URL.revokeObjectURL = vi.fn();
    vi.stubGlobal(
      "fetch",
      vi.fn(
        async () =>
          new Response("x", {
            headers: {
              "Content-Disposition":
                'attachment; filename="avelsprioritet-genbank-1-2026-11-25.csv"',
            },
          }),
      ),
    );
    expect(await downloadExport("/x.csv")).toBeNull();
    expect(click).toHaveBeenCalled();
    expect(document.querySelector("a[download]")).toBeNull();
    vi.advanceTimersByTime(5_000);
    expect(URL.revokeObjectURL).not.toHaveBeenCalled();
    vi.advanceTimersByTime(5_000);
    expect(URL.revokeObjectURL).toHaveBeenCalledWith("blob:x");
    vi.unstubAllGlobals();
  });
});
