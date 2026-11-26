import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";

import type { FounderAtRisk, PopulationMetrics } from "@/redux/api/apiSlice";
import Laget, { lageLines } from "@/components/genetics/Laget";

const metrics = (over: Partial<PopulationMetrics> = {}) =>
  ({
    n_active: 221,
    effective_population_size: 75.4,
    delta_f: 0.0067,
    ...over,
  }) as PopulationMetrics;

const founder = (risk_level: FounderAtRisk["risk_level"]) =>
  ({ founder_id: "G9001-1", risk_level }) as FounderAtRisk;

const levels = (m: PopulationMetrics, f?: FounderAtRisk[]) =>
  lageLines(m, f).map((l) => l.level);

describe("lageLines", () => {
  it("bands Ne on the unrounded value, and the number shown never contradicts its band", () => {
    const one = (ne: number) =>
      lageLines(metrics({ effective_population_size: ne, delta_f: null }))[0];
    expect(one(49.6)).toEqual({
      level: "danger",
      text: "Ne är 49,6, under 50 som FAO anger.",
    });
    expect(one(50)).toEqual({
      level: "warning",
      text: "Ne är 50, minst 50 som FAO anger men under målet 100.",
    });
    expect(one(75.4).text).toBe(
      "Ne är 75, minst 50 som FAO anger men under målet 100.",
    );
    expect(one(99.6)).toEqual({
      level: "warning",
      text: "Ne är 99,6, minst 50 som FAO anger men under målet 100.",
    });
    expect(one(100)).toEqual({
      level: "good",
      text: "Ne är 100, minst 100 som är målet.",
    });
  });

  it("bands ΔF on the unrounded value, agreeing with Ne = 1/(2·ΔF)", () => {
    const one = (delta_f: number) =>
      lageLines(metrics({ effective_population_size: null, delta_f }))[0];
    expect(one(0.0067)).toEqual({
      level: "good",
      text: "Inaveln ökar 0,67\u00a0% per generation, högst 1\u00a0% som FAO anger.",
    });
    expect(one(0.01).level).toBe("good"); // Ne exactly 50: minst 50
    expect(one(0.01004)).toEqual({
      level: "danger",
      text: "Inaveln ökar 1,004\u00a0% per generation, mer än 1\u00a0% som FAO anger.",
    });
    expect(one(0.012).text).toBe(
      "Inaveln ökar 1,20\u00a0% per generation, mer än 1\u00a0% som FAO anger.",
    );
    expect(one(-0.001).text).toBe("Inaveln ökar inte per generation.");
    // The two lines agree at the limit.
    for (const df of [0.0099, 0.01, 0.0101]) {
      expect(
        levels(
          metrics({ effective_population_size: 1 / (2 * df), delta_f: df }),
        ).map((l) => l === "danger"),
      ).toEqual([df > 0.01, df > 0.01]);
    }
  });

  it("counts founderdjur with one carrier left and links to the table", () => {
    const line = lageLines(
      metrics({ effective_population_size: null, delta_f: null }),
      [founder("critical"), founder("critical"), founder("lost")],
    )[0];
    expect(line).toEqual({
      level: "danger",
      text: "2 founderdjur har bara 1 bärare kvar.",
      anchor: "founderdjurens-lage",
    });
    expect(
      lageLines(metrics({ effective_population_size: null, delta_f: null }), [
        founder("ok"),
      ])[0].level,
    ).toBe("good");
  });

  it("adds a line for founderdjur without carriers only when there are possible carriers to look for", () => {
    const none = metrics({ effective_population_size: null, delta_f: null });
    const lost = (recoverable_carriers: string[]) =>
      ({ ...founder("lost"), recoverable_carriers }) as FounderAtRisk;
    expect(
      lageLines(none, [
        founder("critical"),
        lost(["G9002-2301"]),
        lost(["G9002-2302", "G9002-2303"]),
        lost([]),
        founder("lost"),
      ])[1],
    ).toEqual({
      level: "warning",
      text: "2 founderdjur saknar bärare i beräkningen, men det finns möjliga bärare att leta upp.",
      anchor: "founderdjurens-lage",
    });
    // Without possible carriers there is nothing to do, so no line.
    expect(lageLines(none, [founder("ok"), lost([]), founder("lost")])).toEqual(
      [
        {
          level: "good",
          text: "Inget founderdjur har bara 1 bärare kvar.",
        },
      ],
    );
  });

  it("says nothing for an empty genebank, a missing number or founders not yet loaded", () => {
    expect(lageLines(metrics({ n_active: 0 }), [founder("critical")])).toEqual(
      [],
    );
    expect(
      lageLines(metrics({ effective_population_size: null, delta_f: null })),
    ).toEqual([]);
  });
});

describe("Laget", () => {
  afterEach(cleanup);

  it("marks each line with a named icon, not colour alone, and links Se vilka", () => {
    render(
      <Laget
        metrics={metrics()}
        founders={[founder("critical"), founder("ok")]}
      />,
    );
    expect(screen.getByTitle("Bevaka")).toBeDefined();
    expect(screen.getByTitle("Bra")).toBeDefined();
    expect(screen.getByTitle("Åtgärda")).toBeDefined();
    expect(
      screen.getByRole("link", { name: "Se vilka" }).getAttribute("href"),
    ).toBe("#founderdjurens-lage");
  });

  it("scrolls to the founder table without a history entry", () => {
    const table = document.createElement("div");
    table.id = "founderdjurens-lage";
    table.tabIndex = -1;
    table.scrollIntoView = vi.fn();
    document.body.appendChild(table);
    const before = window.history.length;
    render(<Laget metrics={metrics()} founders={[founder("critical")]} />);
    fireEvent.click(screen.getByRole("link", { name: "Se vilka" }));
    expect(table.scrollIntoView).toHaveBeenCalled();
    expect(document.activeElement).toBe(table);
    expect(window.location.hash).toBe("");
    expect(window.history.length).toBe(before);
    table.remove();
  });
});
