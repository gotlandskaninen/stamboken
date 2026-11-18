import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  RabbitRow,
  type RabbitRowProps,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/RabbitRow";
import {
  EMPTY_ENTRY,
  PENDING_SALE_TEXT,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";
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
      "Död",
      "Såld",
    ]);
    expect(radios.some((r) => r.checked)).toBe(false);
  });

  it("shows a later death given without its day as its month only", () => {
    const later = { death_date: "2027-01-10", death_day_known: false };
    render(<RabbitRow {...props({ r: rabbit(1, later) })} />);
    expect(screen.getByText("Dödsfall registrerat januari 2027")).toBeTruthy();
    cleanup();
    render(
      <RabbitRow
        {...props({ r: rabbit(1, { ...later, death_day_known: true }) })}
      />,
    );
    expect(
      screen.getByText("Dödsfall registrerat 10 januari 2027"),
    ).toBeTruthy();
  });

  it("opens the month for Död and keeps the year preselected", () => {
    const onChange = vi.fn();
    const { rerender } = render(<RabbitRow {...props({ onChange })} />);
    fireEvent.click(screen.getByLabelText("Död"));
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

  it("opens the sale dialog for a caretaker, whose sale shows as a proposal", () => {
    const onSell = vi.fn();
    render(<RabbitRow {...props({ canSell: false, onSell })} />);
    fireEvent.click(screen.getByLabelText("Såld"));
    expect(onSell).toHaveBeenCalledWith(1);
    cleanup();
    const sold = {
      ...EMPTY_ENTRY,
      val: "sald" as const,
      sald: { till: "G9002", ar: 2026, manad: 10, dag: 3, kopare: null },
    };
    render(
      <RabbitRow
        {...props({ canSell: false, proposal: true, onSell, entry: sold })}
      />,
    );
    expect(screen.getByText(PENDING_SALE_TEXT)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ändra" }));
    expect(onSell).toHaveBeenCalledTimes(2);
    cleanup();
    // FB5: a sale the owner registered is not the caretaker's to change
    render(<RabbitRow {...props({ canSell: false, entry: sold })} />);
    expect(screen.getByText("Såld till G9002, 3 oktober 2026")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Ändra" })).toBeNull();
    expect(screen.queryByText(PENDING_SALE_TEXT)).toBeNull();
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

  it("marks a rabbit bought during the year, with the seller in the title (4a Task 5)", () => {
    render(
      <RabbitRow
        {...props({
          r: rabbit(1, { kopt: { datum: "2026-05-14", fran: "G9002" } }),
        })}
      />,
    );
    const badge = screen.getByText("Köpt 14 maj");
    expect(badge.getAttribute("title")).toBe("Köpt från G9002");
    cleanup();
    render(
      <RabbitRow
        {...props({
          r: rabbit(1, { kopt: { datum: "2026-01-02", fran: "GX1" } }),
        })}
      />,
    );
    expect(screen.getByText("Köpt 2 januari").getAttribute("title")).toBe(
      "Köpt utanför genbanken",
    );
    cleanup();
    render(<RabbitRow {...props()} />);
    expect(screen.queryByText(/^Köpt/)).toBeNull();
  });
});
