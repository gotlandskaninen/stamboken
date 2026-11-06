import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { GeneticsSummary } from "@/components/individual/GeneticsSummary";
import type { IndividualGeneticsData } from "@/lib/genetics";

const NON_MEMBER =
  "Ingår inte i avelsstammen just nu – jämfört som om den gjorde det";
const base: IndividualGeneticsData = {
  inbreeding: 0.031,
  mean_kinship: 0.0142,
  band: "B",
  band_reason: null,
  in_reference: true,
  alive: true,
  pedigree_completeness: 0.97,
  reference_size: 820,
  definition_version: 2,
  preliminary: true,
  stale: false,
};

afterEach(cleanup);

describe("GeneticsSummary", () => {
  it("shows the band label and F", () => {
    render(<GeneticsSummary data={base} />);
    expect(screen.getByText("B · Värdefull för aveln")).toBeTruthy();
    expect(screen.getByText(/F 3,1\s%/)).toBeTruthy();
  });

  it("opens the info panel on tap with MK, completeness and the preliminary rule", () => {
    render(<GeneticsSummary data={base} />);
    fireEvent.click(screen.getByRole("button", { name: /Om genetiken/ }));
    expect(screen.getByText(/MK 1,4\s%/)).toBeTruthy();
    expect(screen.getByText(/97 % känd stamtavla/)).toBeTruthy();
    expect(screen.getByText(/820 djur/)).toBeTruthy();
    expect(screen.getByText(/preliminär regel/)).toBeTruthy();
  });

  it("keeps the percent sign on the same line and wires the toggle to its panel", () => {
    render(<GeneticsSummary data={base} />);
    expect(screen.getByText(/F 3,1\s%/).textContent).toContain("3,1\u00a0%");
    const btn = screen.getByRole("button", { name: /Om genetiken/ });
    expect(btn.className).toContain("sb-btn ");
    fireEvent.click(btn);
    const id = btn.getAttribute("aria-controls");
    expect(id).toBeTruthy();
    expect(document.getElementById(id!)?.textContent).toMatch(/MK 1,4/);
  });

  it("explains a non-member, with or without a band", () => {
    render(<GeneticsSummary data={{ ...base, in_reference: false }} />);
    expect(screen.getByText(NON_MEMBER)).toBeTruthy();
    cleanup();
    render(
      <GeneticsSummary
        data={{
          ...base,
          in_reference: false,
          band: null,
          band_reason: "incomplete_pedigree",
        }}
      />,
    );
    expect(screen.getByText(NON_MEMBER)).toBeTruthy();
    expect(
      screen.getByText("Stamtavlan är för ofullständig för ett band"),
    ).toBeTruthy();
  });

  it("does not call an animal sold outside the genebank a non-member", () => {
    render(
      <GeneticsSummary
        data={{
          ...base,
          in_reference: false,
          band: null,
          band_reason: "outside_genebank",
        }}
      />,
    );
    expect(screen.getByText("Såld utanför genbanken")).toBeTruthy();
    expect(screen.queryByText(NON_MEMBER)).toBeNull();
    cleanup();
    render(
      <GeneticsSummary
        data={{
          ...base,
          in_reference: false,
          band: null,
          band_reason: "small_reference",
        }}
      />,
    );
    expect(screen.getByText(NON_MEMBER)).toBeTruthy();
  });

  it.each([
    ["outside_genebank", "Såld utanför genbanken"],
    ["incomplete_pedigree", "Stamtavlan är för ofullständig för ett band"],
    ["small_reference", "För få djur i avelsstammen för band"],
  ] as const)("replaces the band for %s", (reason, text) => {
    render(
      <GeneticsSummary data={{ ...base, band: null, band_reason: reason }} />,
    );
    expect(screen.getByText(text)).toBeTruthy();
  });

  it("shows only F for a dead animal", () => {
    render(
      <GeneticsSummary
        data={{
          ...base,
          alive: false,
          band: null,
          mean_kinship: null,
          band_reason: "dead",
          in_reference: false,
        }}
      />,
    );
    expect(screen.queryByText(/Värdefull/)).toBeNull();
    expect(screen.queryByText(NON_MEMBER)).toBeNull();
    expect(screen.getByText(/F 3,1\s%/)).toBeTruthy();
  });

  it("marks a stale result", () => {
    render(<GeneticsSummary data={{ ...base, stale: true }} />);
    expect(screen.getByText("Uppdateras…")).toBeTruthy();
  });
});
