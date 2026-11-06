import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";
import {
  BUYER_PRIVACY_HELP,
  GENETICS_INFO,
  VoidHerdTrackingDialog,
} from "@/components/individual/VoidHerdTrackingDialog";
import type { HerdTrackingRow } from "@/lib/herdTracking";

afterEach(cleanup);

const row = (date: string): HerdTrackingRow => ({
  id: 4,
  date,
  kind: "TRANSFER",
  herd: {
    id: 2,
    herd: "G1300",
    herd_name: "Erikssons",
    outside_genebank: false,
    label: "G1300 – Erikssons",
  },
  from_herd: null,
  voided_at: null,
  voided_reason: null,
  voided_operation_id: null,
  operation_id: "op",
  created_at: `${date}T10:00:00+00:00`,
  confirmed: null,
  notes: null,
  buyer: null,
  can_void: true,
  can_undo_sale: true,
  can_undo_operation: false,
});

const open = (
  props: Partial<React.ComponentProps<typeof VoidHerdTrackingDialog>> = {},
) => {
  const onConfirm = vi.fn();
  render(
    <ThemeProvider theme={createTheme()}>
      <VoidHerdTrackingDialog
        open
        row={row(new Date().toISOString().slice(0, 10))}
        mode="undoSale"
        busy={false}
        error={null}
        onClose={() => {}}
        onConfirm={onConfirm}
        {...props}
      />
    </ThemeProvider>,
  );
  return onConfirm;
};

describe("VoidHerdTrackingDialog", () => {
  it("requires a reason and shows the buyer-privacy help", () => {
    const onConfirm = open();
    expect(screen.getByText(BUYER_PRIVACY_HELP)).toBeDefined();
    const confirm = screen.getByRole("button", { name: "Ångra försäljning" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Anledning"), {
      target: { value: "  Fel köpare  " },
    });
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledWith("Fel köpare", expect.any(String));
  });

  it("keeps one operation id per opening (a double click is one operation)", () => {
    const onConfirm = open();
    fireEvent.change(screen.getByLabelText("Anledning"), {
      target: { value: "Fel" },
    });
    const confirm = screen.getByRole("button", { name: "Ångra försäljning" });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(onConfirm.mock.calls[0][1]).toBe(onConfirm.mock.calls[1][1]);
  });

  it("explains that genetics history is not recomputed for an old row", () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(2026, 5, 1)); // latest snapshot: 2025-12-30
    try {
      open({ row: row("2020-05-01"), mode: "void" });
      expect(screen.getByText(GENETICS_INFO)).toBeDefined();
      cleanup();
      open({ row: row("2026-05-15"), mode: "void" });
      expect(screen.queryByText(GENETICS_INFO)).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shows the server's error inline", () => {
    open({
      error:
        "Försäljningen registrerades för mer än 7 dagar sedan. Kontakta genbanksansvarig.",
    });
    expect(screen.getByRole("alert").textContent).toContain(
      "Kontakta genbanksansvarig.",
    );
  });

  it("replaces a duplicate privacy error with an explanation", () => {
    open({ error: BUYER_PRIVACY_HELP });
    expect(screen.getByRole("alert").textContent).toBe(
      "Texten innehåller en e-postadress eller ett telefonnummer. Ta bort den och försök igen.",
    );
  });

  it("keeps the title stable while the dialog closes", () => {
    const props = {
      busy: false,
      error: null,
      onClose: () => {},
      onConfirm: () => {},
    };
    const ui = (isOpen: boolean, r: HerdTrackingRow | null) => (
      <ThemeProvider theme={createTheme()}>
        <VoidHerdTrackingDialog
          open={isOpen}
          row={r}
          mode={r ? "undoSale" : "void"}
          {...props}
        />
      </ThemeProvider>
    );
    const { rerender } = render(ui(true, row("2026-05-15")));
    rerender(ui(false, null));
    expect(
      screen.getByText("Ångra försäljning", { selector: "h2" }),
    ).toBeDefined();
  });
});
