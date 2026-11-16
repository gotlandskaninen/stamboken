import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { SoldDialog } from "@/app/(app)/stamboken/(dashboard)/arsrapport/SoldDialog";

afterEach(cleanup);

describe("SoldDialog", () => {
  it("saves a changed sale to a herd at once, before the herd list has arrived", () => {
    const onSave = vi.fn();
    render(
      <SoldDialog
        open
        number="M9007-2412"
        year={2025}
        genebankId={2}
        ownHerd="M9007"
        loadHerds={() => new Promise(() => {})} // never answers
        existing={{ till: "M9001", ar: 2025, manad: 12, dag: 31, kopare: null }}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Spara försäljningen" }),
    );
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ till: "M9001", ar: 2025, manad: 12, dag: 31 }),
    );
  });
});
