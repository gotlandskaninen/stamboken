import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import "@/i18n";
import { NumberConflictDialog } from "@/components/herd/NumberConflictDialog";
import type { NumberCheck } from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";

vi.mock("@/lib/mode-context", () => ({ useMode: () => "prod" }));

const check = (kind: string, holder: unknown): NumberCheck =>
  ({
    stamboken_number: null,
    paper_number: "G1-2551",
    status: "conflict",
    conflicts: [{ kind, paper: "5", stamboken: null, holder }],
    choices: ["paper_is_right"],
    actions: [],
  }) as unknown as NumberCheck;

const show = (c: NumberCheck) =>
  render(
    <NumberConflictDialog
      check={c}
      onUseStambokenNumber={() => {}}
      onClose={() => {}}
      isSaving={false}
    />,
  );

describe("NumberConflictDialog litter number conflicts", () => {
  afterEach(cleanup);

  it("explains a taken or too low paper litter number", () => {
    show(check("litter_number_taken", { litter_number: 6 }));
    expect(
      screen.getByText(/Kullnummer 5 finns redan eller ligger före/),
    ).toBeTruthy();
    expect(screen.getByText(/kull 6/)).toBeTruthy();
  });

  it("explains a paper litter number below 1", () => {
    show(check("litter_number_invalid", null));
    expect(
      screen.getByText(/Kullnumret på intyget måste vara 1 eller högre/),
    ).toBeTruthy();
  });
});
