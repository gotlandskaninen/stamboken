import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
// Use the /vitest entry: it extends vitest's imported `expect` directly, so the
// jest-dom matchers work without a global `expect` (this project's
// vitest.config has no `globals: true` / setupFiles).
import "@testing-library/jest-dom/vitest";
import { DemoBanner } from "@/components/public/DemoBanner.client";

describe("DemoBanner", () => {
  afterEach(() => {
    cleanup();
  });

  it("shows the exact Swedish demo text", () => {
    render(<DemoBanner />);
    expect(
      screen.getByText(
        "TESTMILJÖ – här kan du öva fritt. Allt återställs varje natt.",
      ),
    ).toBeInTheDocument();
  });

  it("is unmissable — has no dismiss/close control", () => {
    render(<DemoBanner />);
    // No onClose => MUI renders no close IconButton. Assert both that there is
    // no button at all and no element labelled "close".
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/close/i)).not.toBeInTheDocument();
  });
});
