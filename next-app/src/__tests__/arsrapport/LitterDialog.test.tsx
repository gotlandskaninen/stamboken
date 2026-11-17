import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  ConfirmCountDialog,
  LitterDialog,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/LitterDialog";
import type { Litter } from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(cleanup);

const ok = <T,>(data: T) => Promise.resolve({ ok: true as const, data });
const litter = (over: Partial<Litter> = {}): Litter => ({
  id: 7,
  litter_number: null,
  birth_date: "2026-05-10",
  mother: "G9001-1",
  father: "G9001-3",
  litter_size: 5,
  litter_size6w: 5,
  preliminary: true,
  ...over,
});

function setup(over: Record<string, unknown> = {}) {
  const props = {
    open: true,
    year: 2026,
    loadMothers: vi.fn(() =>
      ok({ honor: [{ id: 1, number: "G9001-1", name: null }] }),
    ),
    loadFathers: vi.fn(() =>
      ok({ hanar: [{ id: 3, number: "G9001-3", name: "Hane" }] }),
    ),
    litters: [litter()],
    add: vi.fn(() => ok({ id: 8, litters: [litter({ id: 8 })] })),
    change: vi.fn(() =>
      ok({ id: 7, litters: [litter({ preliminary: false })] }),
    ),
    onSaved: vi.fn(),
    onClose: vi.fn(),
    ...over,
  };
  render(<LitterDialog {...props} />);
  return props;
}

async function fill(size6w = "") {
  await screen.findByRole("option", { name: "G9001-1" });
  fireEvent.change(screen.getByLabelText("Mor"), { target: { value: "1" } });
  const far = screen.getByRole("combobox", { name: "Far" });
  fireEvent.keyDown(far, { key: "ArrowDown" });
  fireEvent.click(
    await screen.findByRole("option", { name: "G9001-3 – Hane" }),
  );
  fireEvent.change(screen.getByLabelText("Född"), {
    target: { value: "2026-05-10" },
  });
  fireEvent.change(screen.getByLabelText("Antal födda"), {
    target: { value: "5" },
  });
  fireEvent.change(screen.getByLabelText("Levande vid 6 veckor"), {
    target: { value: size6w },
  });
}

describe("LitterDialog", () => {
  it("shows the hint for the 6-week count", () => {
    setup();
    expect(
      screen.getByText(
        "Lämna tomt om kullen är yngre än 6 veckor, så räknar vi alla som levande tills du ändrar.",
      ),
    ).toBeTruthy();
  });

  it("posts the litter and says that it stays if the report is withdrawn", async () => {
    const p = setup();
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Spara kullen" }));
    await waitFor(() => expect(p.add).toHaveBeenCalled());
    expect(p.add).toHaveBeenCalledWith({
      mother_id: 1,
      father_id: 3,
      birth_date: "2026-05-10",
      litter_size: 5,
      litter_size6w: null, // left empty: preliminary
    });
    expect(
      await screen.findByText(
        "Kullen är registrerad i Stamboken nu. Den finns kvar även om du drar tillbaka rapporten.",
      ),
    ).toBeTruthy();
    expect(p.onSaved).toHaveBeenCalledWith([litter({ id: 8 })]);
  });

  it("sends a given 6-week count as a number", async () => {
    const p = setup();
    await fill("3");
    fireEvent.click(screen.getByRole("button", { name: "Spara kullen" }));
    await waitFor(() => expect(p.add).toHaveBeenCalled());
    expect(p.add).toHaveBeenCalledWith(
      expect.objectContaining({ litter_size6w: 3 }),
    );
  });

  it("refuses more alive at 6 weeks than born before anything is sent", async () => {
    const p = setup();
    await fill("9");
    fireEvent.click(screen.getByRole("button", { name: "Spara kullen" }));
    expect(
      await screen.findByText(
        "Antal levande vid 6 veckor kan inte vara fler än antal födda.",
      ),
    ).toBeTruthy();
    expect(p.add).not.toHaveBeenCalled();
  });

  it("asks about the same litter and changes the existing one, with only two choices", async () => {
    const p = setup({
      add: vi.fn(() =>
        Promise.resolve({
          ok: false as const,
          problem: {
            status: 409,
            title: "Konflikt",
            detail: "Modern har redan en kull.",
            extensions: { code: "samma_kull", breeding_id: 7 },
          },
        }),
      ),
    });
    await fill("4");
    fireEvent.click(screen.getByRole("button", { name: "Spara kullen" }));
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Det finns redan en kull efter G9001-1 född 10 maj 2026. Är det samma kull?",
    );
    expect(
      screen.getByText(
        "En hona kan inte få två kullar så tätt. Stämmer inte datumet, ändra den befintliga kullen.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Nej/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Avbryt" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ja, ändra den" }));
    await waitFor(() => expect(p.change).toHaveBeenCalled());
    expect(p.change).toHaveBeenCalledWith(7, {
      litter_size: 5,
      litter_size6w: 4,
    });
    expect(
      await screen.findByText(/Kullen är registrerad i Stamboken nu/),
    ).toBeTruthy();
  });

  it("shows another refusal and keeps what was typed", async () => {
    const p = setup({
      add: vi.fn(() =>
        Promise.resolve({
          ok: false as const,
          problem: {
            status: 422,
            title: "t",
            detail: "Fadern finns inte i Stamboken.",
          },
        }),
      ),
    });
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Spara kullen" }));
    expect(
      await screen.findByText("Fadern finns inte i Stamboken."),
    ).toBeTruthy();
    expect(
      (screen.getByLabelText("Antal födda") as HTMLInputElement).value,
    ).toBe("5");
    expect(p.onSaved).not.toHaveBeenCalled();
  });

  it("offers a retry when the fathers could not be fetched", async () => {
    const loadFathers = vi
      .fn()
      .mockResolvedValueOnce({
        ok: false as const,
        problem: { status: 502, title: "t", detail: "x" },
      })
      .mockResolvedValue({
        ok: true as const,
        data: { hanar: [{ id: 3, number: "G9001-3", name: null }] },
      });
    setup({ loadFathers });
    fireEvent.click(await screen.findByRole("button", { name: "Försök igen" }));
    await waitFor(() => expect(loadFathers).toHaveBeenCalledTimes(2));
  });
});

describe("ConfirmCountDialog", () => {
  it("confirms the count of a preliminary litter, as it stands or changed", async () => {
    const change = vi.fn(() =>
      ok({ id: 7, litters: [litter({ preliminary: false })] }),
    );
    const onSaved = vi.fn();
    render(
      <ConfirmCountDialog
        litter={litter()}
        change={change}
        onSaved={onSaved}
        onClose={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Levande vid 6 veckor"), {
      target: { value: "4" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Bekräfta antalet" }));
    await waitFor(() =>
      expect(change).toHaveBeenCalledWith(7, { litter_size6w: 4 }),
    );
    expect(onSaved).toHaveBeenCalled();
  });

  it("cannot confirm more than were born", () => {
    const change = vi.fn();
    render(
      <ConfirmCountDialog
        litter={litter()}
        change={change}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Levande vid 6 veckor"), {
      target: { value: "6" },
    });
    expect(
      (
        screen.getByRole("button", {
          name: "Bekräfta antalet",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });
});

describe("a network failure", () => {
  const down = () => Promise.reject(new Error("offline"));
  const FALLBACK = "Det gick inte att nå servern. Försök igen.";

  it("keeps the form and shows an error when saving a litter fails", async () => {
    const p = setup({ add: vi.fn(down) });
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Spara kullen" }));
    expect(await screen.findByText(FALLBACK)).toBeTruthy();
    expect(
      (screen.getByLabelText("Antal födda") as HTMLInputElement).value,
    ).toBe("5");
    const save = screen.getByRole("button", {
      name: "Spara kullen",
    }) as HTMLButtonElement;
    expect(save.disabled).toBe(false); // busy is reset: it can be tried again
    p.add.mockImplementation(() => ok({ id: 8, litters: [litter({ id: 8 })] }));
    fireEvent.click(save);
    await waitFor(() => expect(p.onSaved).toHaveBeenCalled());
  });

  it("keeps the question when changing the existing litter fails", async () => {
    const same = () =>
      Promise.resolve({
        ok: false as const,
        problem: {
          status: 409,
          title: "Konflikt",
          detail: "x",
          extensions: { code: "samma_kull", breeding_id: 7 },
        },
      });
    const p = setup({ add: vi.fn(same), change: vi.fn(down) });
    await fill("4");
    fireEvent.click(screen.getByRole("button", { name: "Spara kullen" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Ja, ändra den" }),
    );
    expect(await screen.findByText(FALLBACK)).toBeTruthy();
    const again = screen.getByRole("button", {
      name: "Ja, ändra den",
    }) as HTMLButtonElement;
    expect(again.disabled).toBe(false);
    expect(p.onSaved).not.toHaveBeenCalled();
  });

  it("shows an error and can retry when confirming a count fails", async () => {
    const change = vi.fn(down);
    render(
      <ConfirmCountDialog
        litter={litter()}
        change={change}
        onSaved={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Bekräfta antalet" }));
    expect(await screen.findByText(FALLBACK)).toBeTruthy();
    expect(
      (
        screen.getByRole("button", {
          name: "Bekräfta antalet",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(false);
  });

  it("offers a retry when the does could not be fetched", async () => {
    const loadMothers = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValue({ ok: true as const, data: { honor: [] } });
    setup({ loadMothers });
    const retry = await screen.findAllByRole("button", { name: "Försök igen" });
    fireEvent.click(retry[0]);
    await waitFor(() => expect(loadMothers).toHaveBeenCalledTimes(2));
  });
});
