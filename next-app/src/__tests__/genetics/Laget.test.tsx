import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

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
  it("bands Ne against FAO's 50 and the target 100, on the value as shown", () => {
    for (const [ne, level] of [
      [49.4, "danger"],
      [49.5, "warning"],
      [99.4, "warning"],
      [99.5, "good"],
      [140, "good"],
    ] as const) {
      expect(
        levels(metrics({ effective_population_size: ne, delta_f: null })),
      ).toEqual([level]);
    }
    expect(lageLines(metrics({ delta_f: null }))[0].text).toBe(
      "Ne är 75. Det är över FAO:s gräns 50 men under målet 100.",
    );
  });

  it("bands ΔF against FAO's 1 %, on the value as shown", () => {
    const one = (delta_f: number) =>
      lageLines(metrics({ effective_population_size: null, delta_f }))[0];
    expect(one(0.0067)).toEqual({
      level: "good",
      text: "Inaveln ökar 0,67 % per generation, under FAO:s gräns 1 %.",
    });
    expect(one(0.009949).level).toBe("good");
    expect(one(0.009951).level).toBe("danger"); // shown as 1,00 %
    expect(one(0.012).text).toBe(
      "Inaveln ökar 1,20 % per generation. FAO:s gräns är 1 %.",
    );
    expect(one(-0.001).text).toBe("Inaveln ökar inte per generation.");
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
});
