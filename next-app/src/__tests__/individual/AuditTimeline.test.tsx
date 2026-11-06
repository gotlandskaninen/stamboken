import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";

vi.mock(
  "@/app/(app)/stamboken/(dashboard)/individ/[number]/audit-actions",
  () => ({
    revertAuditEntry: vi.fn(),
    restoreRecord: vi.fn(),
  }),
);
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: vi.fn() }),
}));

import AuditTimeline from "@/components/audit/AuditTimeline";
import type { AuditLogEntry } from "@/app/(app)/stamboken/(dashboard)/individ/[number]/audit-types";

afterEach(cleanup);

const entry = (schema_name: string): AuditLogEntry => ({
  id: 1,
  schema_name,
  operation: "UPDATE",
  changed_fields: ["name"],
  old_data: { name: "Gammal" },
  new_data: { name: "Ny" },
  changed_by: "anna",
  changed_at: "2024-01-02T09:00:00+00:00",
  transaction_id: null,
});

describe("AuditTimeline", () => {
  it("offers undo/restore on trigger rows", () => {
    render(
      <AuditTimeline
        tableName="individual"
        recordId={1}
        entries={[entry("public")]}
      />,
    );
    expect(screen.getByRole("button", { name: /Ångra/ })).toBeTruthy();
    expect(screen.queryByText("Gamla Stamboken")).toBeNull();
  });

  it("marks history imported from the old Stamboken and hides undo/restore", () => {
    render(
      <AuditTimeline
        tableName="individual"
        recordId={1}
        entries={[entry("v1")]}
      />,
    );
    expect(screen.getByText("Gamla Stamboken")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Ångra/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Återställ/ })).toBeNull();
  });
});
