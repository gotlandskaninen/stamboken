// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExportButtons } from "@/app/(app)/medlem/matrikel/ExportButtons";

describe("ExportButtons", () => {
  it("renders both exports as non-submitting buttons", () => {
    render(<ExportButtons />);
    for (const name of ["Exportera MATR", "Exportera Koharen"]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute(
        "type",
        "button",
      );
    }
  });
});
