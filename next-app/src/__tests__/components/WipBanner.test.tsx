import { describe, it, expect, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import { WipBanner } from "@/components/public/WipBanner.client";

const KEY = "herdbook-wip-banner-dismissed";

describe("WipBanner", () => {
  beforeEach(() => {
    cleanup();
    localStorage.clear();
  });

  it("shows by default, then hides and persists on dismiss", async () => {
    render(<WipBanner />);
    expect(await screen.findByText(/nya Stamboken/i)).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText(/close/i));
    await waitFor(() =>
      expect(screen.queryByText(/nya Stamboken/i)).not.toBeInTheDocument(),
    );
    expect(localStorage.getItem(KEY)).toBe("1");
  });

  it("stays hidden when previously dismissed", () => {
    localStorage.setItem(KEY, "1");
    render(<WipBanner />);
    expect(screen.queryByText(/nya Stamboken/i)).not.toBeInTheDocument();
  });
});
