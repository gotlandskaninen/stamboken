import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import {
  HerdTrackingCorrectionDialog,
  isChronological,
} from "@/components/individual/HerdTrackingCorrectionDialog";
import {
  BUYER_PRIVACY_HELP,
  htErrorMessage,
} from "@/components/individual/VoidHerdTrackingDialog";
import type { HerdTrackingHistory } from "@/lib/herdTracking";

afterEach(cleanup);

const history: HerdTrackingHistory = {
  individual: { id: 7, number: "G100-2511" },
  viewer: { can_manage: true },
  rows: [
    {
      id: 21,
      date: "2026-02-01",
      kind: "ATTESTATION",
      herd: {
        id: 1,
        herd: "G100",
        herd_name: null,
        outside_genebank: false,
        label: "G100",
      },
      from_herd: null,
      voided_at: null,
      voided_reason: null,
      voided_operation_id: null,
      operation_id: "op-a",
      created_at: "2026-02-01T10:00:00+00:00",
      confirmed: null,
      notes: null,
      buyer: null,
      can_void: true,
      can_undo_sale: false,
      can_undo_operation: false,
    },
  ],
  periods: [],
};

const loadHerds = vi.fn(async () => ({
  success: true as const,
  herds: [
    { herd: "G100", herd_name: null, is_active: true },
    { herd: "GX1", herd_name: "Utanför genbanken", is_active: true },
  ],
}));

type DialogProps = React.ComponentProps<typeof HerdTrackingCorrectionDialog>;

const dialog = (props: Partial<DialogProps> = {}, onConfirm = vi.fn()) => (
  <ThemeProvider theme={createTheme()}>
    <HerdTrackingCorrectionDialog
      open
      history={history}
      loadHerds={loadHerds}
      busy={false}
      error={null}
      onClose={() => {}}
      onConfirm={onConfirm}
      {...props}
    />
  </ThemeProvider>
);

const renderDialog = (props: Partial<DialogProps> = {}) => {
  const onConfirm = vi.fn();
  const view = render(dialog(props, onConfirm));
  return Object.assign(onConfirm, {
    rerender: (next: Partial<DialogProps>) =>
      view.rerender(dialog(next, onConfirm)),
  });
};

const reportBox = () =>
  screen.getByLabelText(/2026-02-01 · Årsrapport/) as HTMLInputElement;

describe("HerdTrackingCorrectionDialog", () => {
  it("builds the G100-2511 correction: void the report, add the sale out of the genebank", async () => {
    const onConfirm = renderDialog();
    await waitFor(() => expect(loadHerds).toHaveBeenCalled());
    const submit = screen.getByRole("button", { name: "Spara korrigering" });
    expect((submit as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByLabelText(/2026-02-01 · Årsrapport/));
    fireEvent.click(screen.getByRole("button", { name: "Lägg till händelse" }));
    await screen.findByRole("option", { name: "GX1 – Utanför genbanken" });
    fireEvent.change(screen.getByLabelText("Datum"), {
      target: { value: "2025-09-30" },
    });
    fireEvent.change(screen.getByLabelText("Besättning"), {
      target: { value: "GX1" },
    });
    fireEvent.change(screen.getByLabelText("Typ"), {
      target: { value: "TRANSFER" },
    });
    expect((submit as HTMLButtonElement).disabled).toBe(true); // reason missing while voiding
    fireEvent.change(screen.getByLabelText("Anledning"), {
      target: { value: "Såld utanför genbanken" },
    });
    fireEvent.click(submit);

    expect(onConfirm).toHaveBeenCalledWith({
      operation_id: expect.any(String),
      void_ids: [21],
      events: [
        { date: "2025-09-30", herd: "GX1", kind: "TRANSFER", notes: null },
      ],
      reason: "Såld utanför genbanken",
    });
    expect(
      screen.getByText("Skriv inte köparens namn eller kontaktuppgifter."),
    ).toBeDefined();
  });

  it("shows the herd-load error inline", async () => {
    const failing = vi.fn(async () => ({
      success: false as const,
      error: "Kunde inte hämta besättningar.",
    }));
    render(
      <ThemeProvider theme={createTheme()}>
        <HerdTrackingCorrectionDialog
          open
          history={history}
          loadHerds={failing}
          busy={false}
          error={null}
          onClose={() => {}}
          onConfirm={() => {}}
        />
      </ThemeProvider>,
    );
    const alert = await screen.findByRole("alert");
    expect(alert.textContent).toContain("Kunde inte hämta besättningar.");
  });

  it("asks for a reason only when a row is voided (the server stores it only then)", async () => {
    const onConfirm = renderDialog();
    await waitFor(() => expect(loadHerds).toHaveBeenCalled());
    expect(screen.queryByLabelText("Anledning")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Lägg till händelse" }));
    await screen.findByRole("option", { name: "GX1 – Utanför genbanken" });
    fireEvent.change(screen.getByLabelText("Datum"), {
      target: { value: "2025-09-30" },
    });
    fireEvent.change(screen.getByLabelText("Besättning"), {
      target: { value: "GX1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara korrigering" }));
    expect(onConfirm).toHaveBeenCalledWith(
      expect.objectContaining({ void_ids: [], reason: "" }),
    );
    fireEvent.click(reportBox());
    expect(screen.getByLabelText("Anledning")).toBeDefined();
  });

  it("pre-checks the rows of a 409 so the manager can resave in one step", async () => {
    const view = renderDialog();
    await waitFor(() => expect(loadHerds).toHaveBeenCalled());
    expect(reportBox().checked).toBe(false);
    const detail =
      "Det finns redan händelser samma dag. Ångra dem i samma korrigering och mata in hela dagen i rätt ordning.";
    view.rerender({ error: detail, conflictRowIds: [21, 999] });
    expect(reportBox().checked).toBe(true);
    expect(screen.getByRole("alert").textContent).toBe(detail);
    expect(screen.getByLabelText("Anledning")).toBeDefined();
  });

  it("explains a privacy rejection with the void dialog's wording", async () => {
    renderDialog({ error: BUYER_PRIVACY_HELP });
    await waitFor(() => expect(loadHerds).toHaveBeenCalled());
    expect(screen.getByRole("alert").textContent).toBe(
      htErrorMessage(BUYER_PRIVACY_HELP),
    );
    expect(htErrorMessage(BUYER_PRIVACY_HELP)).not.toBe(BUYER_PRIVACY_HELP);
  });

  it("scrolls a new error into view and focuses it", async () => {
    const scrollIntoView = vi.fn();
    Element.prototype.scrollIntoView = scrollIntoView;
    const view = renderDialog();
    await waitFor(() => expect(loadHerds).toHaveBeenCalled());
    expect(scrollIntoView).not.toHaveBeenCalled();
    view.rerender({ error: "Raderna finns inte eller är redan ångrade." });
    const alert = screen.getByRole("alert");
    await waitFor(() => expect(document.activeElement).toBe(alert));
    expect(scrollIntoView).toHaveBeenCalled();
  });

  it("isChronological", () => {
    const e = (date: string) => ({
      date,
      herd: "G1",
      kind: "TRANSFER" as const,
      notes: null,
    });
    expect(
      isChronological([e("2025-01-01"), e("2025-01-01"), e("2025-02-01")]),
    ).toBe(true);
    expect(isChronological([e("2025-02-01"), e("2025-01-01")])).toBe(false);
  });
});
