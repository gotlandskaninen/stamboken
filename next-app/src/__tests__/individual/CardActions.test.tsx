import React from "react";
import { describe, it, expect, afterEach, beforeAll, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { ThemeProvider, createTheme } from "@mui/material/styles";

// individual-detail pulls in server actions and the redux store; only the
// presentational CardActions is under test.
vi.mock("@/app/(app)/stamboken/(dashboard)/individ/[number]/actions", () => ({
  updateIndividual: vi.fn(),
  getGenebankHerds: vi.fn(),
  voidHerdTracking: vi.fn(),
  correctHerdTracking: vi.fn(),
  undoHerdTrackingOperation: vi.fn(),
}));
vi.mock(
  "@/app/(app)/stamboken/(dashboard)/individ/[number]/audit-types",
  () => ({}),
);
vi.mock("@/components/audit/AuditTimeline", () => ({ default: () => null }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

import { CardActions } from "@/app/(app)/stamboken/(dashboard)/individ/[number]/individual-detail";

beforeAll(async () => {
  await import("@/i18n");
});
afterEach(cleanup);

const noop = () => {};
const renderActions = (
  canEdit: boolean,
  onUndoSale: (() => void) | null = null,
) =>
  render(
    <ThemeProvider theme={createTheme()}>
      <CardActions
        canEdit={canEdit}
        isEditing={false}
        onToggleEdit={noop}
        isAlive
        onReportDeath={noop}
        onUndoDeath={noop}
        canSell={false}
        onSell={noop}
        testMateHref="/stamboken/provparning?hona=G1-1"
        onUndoSale={onUndoSale}
      />
    </ThemeProvider>,
  );

describe("CardActions", () => {
  it("offers Provpara to a non-editor, and nothing that edits", () => {
    renderActions(false);
    expect(screen.queryByRole("button", { name: "Redigera" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder" }));
    const item = screen.getByRole("menuitem", { name: "Provpara" });
    expect(item.getAttribute("href")).toBe("/stamboken/provparning?hona=G1-1");
    expect(screen.queryByText("Rapportera död")).toBeNull();
    expect(screen.queryByText("Redigera")).toBeNull();
  });

  it("an editor still gets the edit button and the edit-only items", () => {
    renderActions(true);
    expect(screen.getByRole("button", { name: "Redigera" })).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder" }));
    expect(screen.getByRole("menuitem", { name: "Provpara" })).toBeDefined();
    expect(screen.getByText("Rapportera död")).toBeDefined();
  });

  it("offers 'Ångra försäljning' to the seller who can no longer edit the rabbit (Review Focus 1)", () => {
    const onUndoSale = vi.fn();
    renderActions(false, onUndoSale);
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder" }));
    fireEvent.click(
      screen.getByRole("menuitem", { name: "Ångra försäljning" }),
    );
    expect(onUndoSale).toHaveBeenCalled();
  });

  it("hides 'Ångra försäljning' when the server does not allow it", () => {
    renderActions(true, null);
    fireEvent.click(screen.getByRole("button", { name: "Fler åtgärder" }));
    expect(
      screen.queryByRole("menuitem", { name: "Ångra försäljning" }),
    ).toBeNull();
  });
});
