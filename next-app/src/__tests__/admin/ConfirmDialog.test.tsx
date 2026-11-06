// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

import { ConfirmDialog } from "@/app/(app)/stamboken/(dashboard)/admin/_components/ConfirmDialog";

afterEach(cleanup);

const confirmBtn = () => screen.getByRole("button", { name: "Ta bort" });
const cancelBtn = () => screen.getByRole("button", { name: "Avbryt" });

describe("ConfirmDialog busy state", () => {
  it("fires onConfirm once per click when idle", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        open
        title="Ta bort person?"
        body="Detta går inte att ångra."
        confirmLabel="Ta bort"
        onConfirm={onConfirm}
        onClose={() => {}}
      />,
    );
    expect(confirmBtn()).toBeEnabled();
    fireEvent.click(confirmBtn());
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("disables both buttons and ignores close while the action is in flight", () => {
    const onConfirm = vi.fn();
    const onClose = vi.fn();
    render(
      <ConfirmDialog
        open
        busy
        title="Ta bort person?"
        body="Detta går inte att ångra."
        confirmLabel="Ta bort"
        onConfirm={onConfirm}
        onClose={onClose}
      />,
    );
    expect(confirmBtn()).toBeDisabled();
    expect(cancelBtn()).toBeDisabled();
    // A second click on a disabled MUI Button never reaches the handler —
    // the double-click that used to fire PersonsCard's mutation twice.
    fireEvent.click(confirmBtn());
    fireEvent.click(cancelBtn());
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    expect(onConfirm).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });
});
