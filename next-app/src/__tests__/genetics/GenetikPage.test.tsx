import React from "react";
import { describe, it, expect, afterEach, beforeEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
  within,
} from "@testing-library/react";

const user = vi.fn();

// Next (14.1+) feeds history.pushState and popstate into useSearchParams. The double does
// the same from window.location; the browser check covers the real router.
vi.mock("next/navigation", async () => {
  const { useMemo, useSyncExternalStore } = await import("react");
  const subscribe = (onChange: () => void) => {
    window.addEventListener("popstate", onChange);
    window.addEventListener("test-pushstate", onChange);
    return () => {
      window.removeEventListener("popstate", onChange);
      window.removeEventListener("test-pushstate", onChange);
    };
  };
  return {
    useSearchParams: () => {
      const search = useSyncExternalStore(
        subscribe,
        () => window.location.search,
      );
      return useMemo(() => new URLSearchParams(search), [search]);
    },
  };
});
vi.mock("@/hooks/useAuth", () => ({ default: () => ({ user: user() }) }));
vi.mock("@/components/genetics/OverviewTab", () => ({
  default: ({ genebankId }: { genebankId: number }) => (
    <p>Översikt för genbank {genebankId}</p>
  ),
}));
vi.mock("@/components/genetics/PrioritiesTab", () => ({
  default: () => <p>Avelsprioritet visas</p>,
}));
vi.mock("@/components/genetics/BreedingSuggestionsTab", () => ({
  default: () => <p>Parningsförslag visas</p>,
}));

import GenetikPage from "@/app/(app)/stamboken/(dashboard)/genetik/page";

const pushState = window.history.pushState.bind(window.history);

describe("Genetik page URL", () => {
  beforeEach(() => {
    vi.spyOn(window.history, "pushState").mockImplementation((...args) => {
      pushState(...args);
      window.dispatchEvent(new Event("test-pushstate"));
    });
  });
  afterEach(() => {
    cleanup();
    vi.restoreAllMocks();
  });

  const open = (search: string, who = { is_manager: [1], is_admin: false }) => {
    window.history.replaceState(null, "", `/stamboken/genetik${search}`);
    user.mockReturnValue(who);
    return render(<GenetikPage />);
  };

  it("opens the tab and genebank in the URL, and Översikt for an unknown tab", () => {
    open("?genebank=2&tab=prioriteringar", { is_manager: [], is_admin: true });
    expect(screen.getByText("Avelsprioritet visas")).toBeDefined();
    cleanup();
    open("?genebank=2&tab=nagot");
    expect(screen.getByText("Översikt för genbank 2")).toBeDefined();
  });

  it("writes the chosen tab to the URL, and Back shows the tab before", async () => {
    open("?genebank=1");
    expect(screen.getByText("Översikt för genbank 1")).toBeDefined();

    fireEvent.click(screen.getByRole("tab", { name: "Avelsprioritet" }));
    expect(window.location.search).toBe("?genebank=1&tab=prioriteringar");
    expect(screen.getByText("Avelsprioritet visas")).toBeDefined();

    window.history.back();
    await waitFor(() =>
      expect(screen.getByText("Översikt för genbank 1")).toBeDefined(),
    );
    expect(window.location.search).toBe("?genebank=1");
  });

  it("writes the chosen genebank to the URL and keeps the tab", () => {
    open("?tab=prioriteringar", { is_manager: [], is_admin: true });
    expect(screen.getByText(/Välj en genbank/)).toBeDefined();

    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(
      within(screen.getByRole("listbox")).getByText("Mellerudskanin"),
    );
    expect(window.location.search).toBe("?tab=prioriteringar&genebank=2");
    expect(screen.getByText("Avelsprioritet visas")).toBeDefined();
  });
});
