import { describe, it, expect, vi, afterEach } from "vitest";

import type { GeneticPriority } from "@/redux/api/apiSlice";
import {
  byHerd,
  downloadExport,
  prioritiesCsvUrl,
  sexLabel,
} from "@/components/genetics/workList";

const row = (
  individual_id: string,
  priority: GeneticPriority["priority"],
  herd: string,
): GeneticPriority => ({
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
  it("asks the server for the chosen levels and order, on the API of the mode shown", () => {
    expect(
      prioritiesCsvUrl("prod", "/api-test", 1, ["critical", "normal"], true),
    ).toBe(
      "/api/v2/genetics/1/priorities.csv?levels=critical,normal&per_herd=1",
    );
    expect(prioritiesCsvUrl("demo", "/api-test", 2, ["critical"], false)).toBe(
      "/api-test/v2/genetics/2/priorities.csv?levels=critical",
    );
    // Base dev without a test API: demo stays on /api, as the RTK baseQuery does.
    expect(prioritiesCsvUrl("demo", undefined, 1, ["critical"], false)).toBe(
      "/api/v2/genetics/1/priorities.csv?levels=critical",
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
