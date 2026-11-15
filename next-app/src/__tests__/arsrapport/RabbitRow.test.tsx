import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  RabbitRow,
  type RabbitRowProps,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/RabbitRow";
import { EMPTY_ENTRY } from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";
import { rabbit } from "./fixtures";

afterEach(cleanup);

const props = (over: Partial<RabbitRowProps> = {}): RabbitRowProps => ({
  r: rabbit(1),
  entry: undefined,
  ending: false,
  year: 2026,
  canSell: true,
  done: false,
  onChange: vi.fn(),
  onSell: vi.fn(),
  onNextWeight: vi.fn(),
  ...over,
});

describe("RabbitRow", () => {
  it("is a fieldset whose legend has the number and the name, with three unchosen radios", () => {
    render(<RabbitRow {...props()} />);
    const group = screen.getByRole("group", { name: "G9001-1 Kanin1" });
    expect(group.tagName).toBe("FIELDSET");
    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios.map((r) => r.parentElement?.textContent)).toEqual([
      "Finns kvar",
      "Död eller slaktad",
      "Såld",
    ]);
    expect(radios.some((r) => r.checked)).toBe(false);
  });

  it("opens the month for Död and keeps the year preselected", () => {
    const onChange = vi.fn();
    const { rerender } = render(<RabbitRow {...props({ onChange })} />);
    fireEvent.click(screen.getByLabelText("Död eller slaktad"));
    const patch = onChange.mock.calls[0][1];
    expect(patch.val).toBe("dod");
    expect(patch.dod.ar).toBe(2026);
    rerender(<RabbitRow {...props({ entry: { ...EMPTY_ENTRY, ...patch } })} />);
    expect(screen.getByLabelText("Månad")).toBeTruthy();
    expect(screen.getByText("Slaktad")).toBeTruthy();
  });

  it("offers the weight, Ej vägd with its reasons, and the gram and range hints", () => {
    const onChange = vi.fn();
    render(
      <RabbitRow
        {...props({
          onChange,
          entry: { ...EMPTY_ENTRY, val: "kvar", vikt: "2800" },
        })}
      />,
    );
    expect(screen.getByText("Menade du 2,8 kg?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ja, 2,8 kg" }));
    expect(onChange).toHaveBeenCalledWith(1, { vikt: "2,8" });
    cleanup();
    render(
      <RabbitRow
        {...props({
          onChange,
          entry: { ...EMPTY_ENTRY, val: "kvar", vikt: "72" },
        })}
      />,
    );
    expect(screen.getByText("Menade du 7,2 kg?")).toBeTruthy();
    expect(screen.queryByText("Stämmer 72 kg?")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Ja, 7,2 kg" }));
    expect(onChange).toHaveBeenLastCalledWith(1, { vikt: "7,2" });
    cleanup();
    render(
      <RabbitRow
        {...props({ entry: { ...EMPTY_ENTRY, val: "kvar", vikt: "7,2" } })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Ja, det stämmer" }));
    expect(screen.queryByText("Stämmer 7,2 kg?")).toBeNull();
    cleanup();
    render(
      <RabbitRow
        {...props({ entry: { ...EMPTY_ENTRY, val: "kvar", ej_vagd: "" } })}
      />,
    );
    for (const t of [
      "Hann inte väga",
      "Har ingen våg",
      "Dräktig eller digivande",
      "Annat …",
    ])
      expect(screen.getByRole("button", { name: t })).toBeTruthy();
  });

  it("sends Enter in the weight field on to the next one", () => {
    const onNextWeight = vi.fn();
    render(
      <RabbitRow
        {...props({ onNextWeight, entry: { ...EMPTY_ENTRY, val: "kvar" } })}
      />,
    );
    fireEvent.keyDown(screen.getByLabelText("Vikt"), { key: "Enter" });
    expect(onNextWeight).toHaveBeenCalledWith(1);
  });

  it("shows Såld as disabled to a caretaker and explains why", () => {
    const onSell = vi.fn();
    render(<RabbitRow {...props({ canSell: false, onSell })} />);
    const sold = screen.getByLabelText("Såld");
    expect(sold.getAttribute("aria-disabled")).toBe("true");
    fireEvent.click(sold);
    expect(onSell).not.toHaveBeenCalled();
    expect(
      screen.getByText(
        "Försäljningen registreras av ägaren eller genbanksansvarig.",
      ),
    ).toBeTruthy();
  });

  it("shows a kept ej_angiven and a rabbit counted by its move without asking", () => {
    render(
      <RabbitRow
        {...props({ entry: { ...EMPTY_ENTRY, val: "ej_angiven" } })}
      />,
    );
    expect(screen.getByText("Ej angiven på blanketten")).toBeTruthy();
    cleanup();
    render(
      <RabbitRow
        {...props({
          r: rabbit(2, {
            state: "via_flytt",
            later: { kind: "TRANSFER", date: "2027-01-03" },
          }),
        })}
      />,
    );
    expect(screen.getByText(/räknas via flytten/)).toBeTruthy();
    expect(screen.queryAllByRole("radio")).toHaveLength(0);
  });
});
