import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { HerdHistorySection } from "@/components/individual/HerdHistorySection";
import type {
  HerdRef,
  HerdTrackingHistory,
  HerdTrackingRow,
} from "@/lib/herdTracking";

afterEach(cleanup);

const herd = (code: string, name: string | null, outside = false): HerdRef => ({
  id: 1,
  herd: code,
  herd_name: name,
  outside_genebank: outside,
  label: outside ? "Såld utanför genbanken" : name ? `${code} – ${name}` : code,
});

const row = (over: Partial<HerdTrackingRow>): HerdTrackingRow => ({
  id: 1,
  date: "2024-01-01",
  kind: "BIRTH",
  herd: herd("G1274", "Lundbergs"),
  from_herd: null,
  voided_at: null,
  voided_reason: null,
  voided_operation_id: null,
  operation_id: "op",
  created_at: "2024-01-01T10:00:00+00:00",
  confirmed: null,
  notes: null,
  buyer: null,
  can_void: false,
  can_undo_sale: false,
  can_undo_operation: false,
  ...over,
});

const history = (
  over: Partial<HerdTrackingHistory> = {},
): HerdTrackingHistory => ({
  individual: { id: 7, number: "G1274-2401" },
  viewer: { can_manage: false },
  rows: [
    row({
      id: 4,
      date: "2025-09-30",
      kind: "TRANSFER",
      herd: herd("GX1", "Utanför", true),
      can_void: true,
    }),
    row({
      id: 3,
      date: "2025-06-01",
      kind: "TRANSFER",
      herd: herd("G1300", "Erikssons"),
      voided_at: "2025-06-02T08:00:00+00:00",
      voided_reason: "Fel köpare",
    }),
    row({ id: 2, date: "2025-01-15", kind: "ATTESTATION" }),
    row({ id: 1 }),
  ],
  periods: [
    {
      herd: herd("G1274", "Lundbergs"),
      from_date: "2024-01-01",
      to_date: "2025-09-30",
      start_kind: "BIRTH",
      start_row_id: 1,
      attestation_ids: [2],
    },
    {
      herd: herd("GX1", "Utanför", true),
      from_date: "2025-09-30",
      to_date: null,
      start_kind: "TRANSFER",
      start_row_id: 4,
      attestation_ids: [],
    },
  ],
  ...over,
});

describe("HerdHistorySection", () => {
  it("shows periods by default, newest first, with the outside label and an open end", () => {
    render(<HerdHistorySection history={history()} />);
    const periods = screen.getAllByTestId("ht-period");
    expect(periods[0].textContent).toContain("Såld utanför genbanken");
    expect(periods[0].textContent).toContain("2025-09-30 – nu");
    expect(periods[1].textContent).toContain("G1274 – Lundbergs");
    expect(periods[1].textContent).toContain("1 årsrapport");
  });

  it("'Visa allt' lists rows in the server's order and hides voided rows for owners", () => {
    render(<HerdHistorySection history={history()} />);
    fireEvent.click(screen.getByRole("button", { name: "Visa allt" }));
    const rows = screen.getAllByTestId("ht-row");
    expect(rows.map((r) => r.textContent?.slice(0, 10))).toEqual([
      "2025-09-30",
      "2025-01-15",
      "2024-01-01",
    ]);
    expect(screen.queryByText("Fel köpare")).toBeNull();
    fireEvent.click(screen.getByLabelText("Visa ångrade"));
    expect(screen.getByText("Fel köpare")).toBeDefined();
    expect(screen.getByText("Ångrad")).toBeDefined();
  });

  it("shows voided rows by default for managers", () => {
    render(
      <HerdHistorySection
        history={history({ viewer: { can_manage: true } })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Visa allt" }));
    expect(screen.getByText("Fel köpare")).toBeDefined();
  });

  it("never re-sorts a same-day TRANSFER + replacing BIRTH", () => {
    const sameDay = history({
      rows: [
        row({
          id: 10,
          date: "2024-03-01",
          kind: "TRANSFER",
          herd: herd("G1300", "Erikssons"),
        }),
        row({ id: 11, date: "2024-03-01", kind: "BIRTH" }),
      ],
    });
    render(<HerdHistorySection history={sameDay} />);
    fireEvent.click(screen.getByRole("button", { name: "Visa allt" }));
    const rows = screen.getAllByTestId("ht-row");
    expect(rows[0].textContent).toContain("Flytt");
    expect(rows[1].textContent).toContain("Född");
  });

  it("marks unconfirmed Phase 10 transfers", () => {
    render(
      <HerdHistorySection
        history={history({
          rows: [row({ kind: "TRANSFER", confirmed: false })],
        })}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Visa allt" }));
    expect(screen.getByText("ej bekräftad")).toBeDefined();
  });

  it("shows the buyer's name and town only when the API returns them", () => {
    const outside = {
      kind: "TRANSFER" as const,
      herd: herd("GX1", null, true),
    };
    const buyer = { id: 3, name: "Anna Köpare", town: "Visby" };
    const { rerender } = render(
      <HerdHistorySection history={history({ rows: [row(outside)] })} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Visa allt" }));
    expect(screen.queryByText(/Köpare:/)).toBeNull();
    rerender(
      <HerdHistorySection
        history={history({ rows: [row({ ...outside, buyer })] })}
      />,
    );
    expect(screen.getByText("Köpare: Anna Köpare, Visby")).toBeDefined();
  });

  it("offers Ångra only where the server allows it", () => {
    const onVoid = vi.fn();
    render(<HerdHistorySection history={history()} onVoid={onVoid} />);
    fireEvent.click(screen.getByRole("button", { name: "Visa allt" }));
    const buttons = screen.getAllByRole("button", { name: "Ångra" });
    expect(buttons).toHaveLength(1);
    fireEvent.click(buttons[0]);
    expect(onVoid).toHaveBeenCalledWith(expect.objectContaining({ id: 4 }));
  });

  it("shows 'Korrigera historik' only to managers", () => {
    const onCorrect = vi.fn();
    const { rerender } = render(
      <HerdHistorySection history={history()} onCorrect={onCorrect} />,
    );
    expect(
      screen.queryByRole("button", { name: "Korrigera historik" }),
    ).toBeNull();
    rerender(
      <HerdHistorySection
        history={history({ viewer: { can_manage: true } })}
        onCorrect={onCorrect}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Korrigera historik" }));
    expect(onCorrect).toHaveBeenCalled();
  });

  it("handles a failed fetch and an empty history", () => {
    const { rerender } = render(<HerdHistorySection history={null} />);
    expect(
      screen.getByText("Besättningshistoriken kunde inte hämtas."),
    ).toBeDefined();
    rerender(
      <HerdHistorySection history={history({ rows: [], periods: [] })} />,
    );
    expect(
      screen.getByText("Ingen besättningshistorik registrerad."),
    ).toBeDefined();
  });

  it("keeps 'Korrigera historik' for managers when there is no history yet", () => {
    const onCorrect = vi.fn();
    const empty = { rows: [], periods: [] };
    const { rerender } = render(
      <HerdHistorySection history={history(empty)} onCorrect={onCorrect} />,
    );
    expect(
      screen.queryByRole("button", { name: "Korrigera historik" }),
    ).toBeNull();
    rerender(
      <HerdHistorySection
        history={history({ ...empty, viewer: { can_manage: true } })}
        onCorrect={onCorrect}
      />,
    );
    expect(
      screen.getByText("Ingen besättningshistorik registrerad."),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Korrigera historik" }));
    expect(onCorrect).toHaveBeenCalled();
  });

  it("shows the empty text when every row is hidden as voided", () => {
    const voided = history({
      rows: [
        row({
          id: 1,
          voided_at: "2025-06-02T08:00:00+00:00",
          voided_reason: "Fel",
        }),
      ],
    });
    render(<HerdHistorySection history={voided} />);
    fireEvent.click(screen.getByRole("button", { name: "Visa allt" }));
    expect(screen.queryAllByTestId("ht-row")).toHaveLength(0);
    expect(
      screen.getByText("Ingen besättningshistorik registrerad."),
    ).toBeDefined();
    fireEvent.click(screen.getByLabelText("Visa ångrade"));
    expect(screen.getAllByTestId("ht-row")).toHaveLength(1);
  });
});
