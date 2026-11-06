import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import "@/i18n";
import { LitterRoster } from "@/components/herd/LitterRoster";
import type { RosterBunny } from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";

const { getLitterRoster, patchBunny } = vi.hoisted(() => ({
  getLitterRoster: vi.fn(),
  patchBunny: vi.fn(),
}));

vi.mock("@/app/(app)/stamboken/(dashboard)/min-besattning/actions", () => ({
  getLitterRoster,
  patchBunny,
  addBunnies: vi.fn(),
  reorderRoster: vi.fn(),
}));

function kit(
  id: number,
  fate: string = "undecided",
  individual: Record<string, unknown> | null = null,
): RosterBunny {
  return {
    id,
    breeding_id: 1,
    slot_order: id,
    observed_sex: null,
    observed_color: null,
    label: null,
    notes: null,
    fate: fate as RosterBunny["fate"],
    provisional_number: individual ? null : `G1-251${id}`,
    individual,
  };
}

// 5 alive (registered, 3 undecided, kept unregistered), 1 died, 1 culled; 3 alive at 6 weeks
const roster = [
  kit(1, "registered", { number: "G1-2511" }),
  kit(2),
  kit(3),
  kit(4),
  kit(5, "kept_unregistered"),
  kit(6, "died"),
  kit(7, "culled"),
];

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LitterRoster out of sync with alive at 6 weeks", () => {
  it("warns and marks the confirmed selection dead, nothing before", async () => {
    getLitterRoster.mockResolvedValue({ success: true, data: roster });
    patchBunny.mockResolvedValue({ success: true, data: {} });
    render(
      <LitterRoster
        breeding={{
          id: 1,
          birth_date: "2025-01-10",
          litter_size: 7,
          litter_size6w: 3,
        }}
        herdId="G1"
      />,
    );

    await screen.findByText(
      "Kullen har 5 levande i rostern men 3 levande vid 6 veckor. Markera 2 kaniner som döda innan intyg kan utfärdas.",
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Välj kaniner att markera som döda" }),
    );

    const box = (position: number) =>
      screen.queryByLabelText(
        `Markera unge ${position} som död`,
      ) as HTMLInputElement | null;
    expect([2, 3, 4, 5].map((p) => box(p)?.checked)).toEqual([
      false,
      true,
      true,
      false,
    ]);
    expect(box(1)).toBeNull(); // registered
    expect(box(6)).toBeNull(); // already dead
    expect(box(7)).toBeNull(); // culled
    expect(patchBunny).not.toHaveBeenCalled();

    // The breeder knows kit 2 died, not kit 4
    fireEvent.click(box(4)!);
    fireEvent.click(box(2)!);
    fireEvent.click(screen.getByRole("button", { name: "Markera 2 som döda" }));

    await waitFor(() => expect(patchBunny).toHaveBeenCalledTimes(2));
    expect(patchBunny).toHaveBeenCalledWith(3, { fate: "died" });
    expect(patchBunny).toHaveBeenCalledWith(2, { fate: "died" });
  });

  it("leaves out a kit whose fate changed while choosing", async () => {
    getLitterRoster.mockResolvedValue({ success: true, data: roster });
    patchBunny.mockResolvedValue({ success: true, data: {} });
    render(
      <LitterRoster
        breeding={{ id: 1, birth_date: "2025-01-10", litter_size6w: 3 }}
        herdId="G1"
      />,
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Välj kaniner att markera som döda",
      }),
    );
    // Kit 4 (preselected) is marked Slaktad inline: 4 alive, 1 left to mark
    fireEvent.change(screen.getAllByLabelText("Öde")[3], {
      target: { value: "culled" },
    });
    const confirm = (await screen.findByRole("button", {
      name: "Markera 1 som döda",
    })) as HTMLButtonElement;
    await waitFor(() => expect(confirm.disabled).toBe(false)); // the fate save
    fireEvent.click(confirm);

    await waitFor(() => expect(patchBunny).toHaveBeenCalledTimes(2));
    expect(patchBunny.mock.calls).toEqual([
      [4, { fate: "culled" }],
      [3, { fate: "died" }],
    ]);
  });

  it("shows no warning when the roster agrees", async () => {
    getLitterRoster.mockResolvedValue({ success: true, data: roster });
    render(
      <LitterRoster
        breeding={{ id: 1, birth_date: "2025-01-10", litter_size6w: 5 }}
        herdId="G1"
      />,
    );
    await screen.findAllByTestId("kit-row");
    expect(screen.queryByText(/levande vid 6 veckor/)).toBeNull();
  });
});
