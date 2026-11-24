// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExportButtons } from "@/app/(app)/medlem/matrikel/ExportButtons";

describe("ExportButtons", () => {
  it("renders the exports as non-submitting buttons and an unnamed checkbox", () => {
    render(<ExportButtons />);
    for (const name of [
      "Exportera MATR",
      "Exportera Koharen",
      "Exportera adresslista",
    ]) {
      expect(screen.getByRole("button", { name })).toHaveAttribute(
        "type",
        "button",
      );
    }
    // No name: inside the matrikel filter form it must not join the query.
    expect(
      screen.getByRole("checkbox", { name: "Med Betala nu" }),
    ).not.toHaveAttribute("name");
  });
});
