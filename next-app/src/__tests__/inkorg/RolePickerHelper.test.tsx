import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { RolePicker } from "@/app/(app)/stamboken/(dashboard)/admin/_components/RolePicker";
import { roleSummaryLabel } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/roleSummaryLabel";

afterEach(cleanup);

describe("genebank helper role", () => {
  it("is grantable per genebank with a numeric id", () => {
    const onGrant = vi.fn();
    render(
      <RolePicker
        genebanks={[{ id: 1, name: "Testgenbank" }]}
        herds={[]}
        defaultLevel="helper"
        onGrant={onGrant}
      />,
    );
    fireEvent.mouseDown(screen.getByLabelText("Genbank"));
    fireEvent.click(
      within(screen.getByRole("listbox")).getByText("Testgenbank"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Lägg till roll" }));
    expect(onGrant).toHaveBeenCalledWith({ level: "helper", genebank: 1 });
  });

  it("is labelled in the role summary", () => {
    expect(roleSummaryLabel("helper(G)")).toBe("Genbankshjälpare (G)");
  });
});
