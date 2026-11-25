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
const mounts = vi.hoisted(() => ({ n: 0 }));
vi.mock("@/components/genetics/PrioritiesTab", async () => {
  const { useState } = await import("react");
  return {
    default: function Priorities() {
      const [mount] = useState(() => ++mounts.n);
      return <p data-mount={mount}>Avelsprioritet visas</p>;
    },
  };
});
vi.mock("@/components/genetics/BreedingSuggestionsTab", () => ({
  default: () => <p>Parningsförslag visas</p>,
}));

import GenetikPage from "@/app/(app)/stamboken/(dashboard)/genetik/page";

const pushState = window.history.pushState.bind(window.history);
const replaceState = window.history.replaceState.bind(window.history);

describe("Genetik page URL", () => {
  beforeEach(() => {
    vi.spyOn(window.history, "pushState").mockImplementation((...args) => {
      pushState(...args);
      window.dispatchEvent(new Event("test-pushstate"));
    });
    vi.spyOn(window.history, "replaceState").mockImplementation((...args) => {
      replaceState(...args);
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
    open("?genebank=2&tab=nagot", { is_manager: [], is_admin: true });
    expect(screen.getByText("Översikt för genbank 2")).toBeDefined();
  });

  it("writes the default genebank to the URL, so tabs, Back, Forward and a copied link keep it", async () => {
    open(""); // the menu's link has no parameters
    const entries = window.history.length;
    await waitFor(() => expect(window.location.search).toBe("?genebank=1"));
    expect(window.history.length).toBe(entries);

    fireEvent.click(screen.getByRole("tab", { name: "Avelsprioritet" }));
    expect(window.location.search).toBe("?genebank=1&tab=prioriteringar");
    window.history.back();
    await waitFor(() =>
      expect(screen.getByText("Översikt för genbank 1")).toBeDefined(),
    );
    expect(window.location.search).toBe("?genebank=1");
    window.history.forward();
    await waitFor(() =>
      expect(screen.getByText("Avelsprioritet visas")).toBeDefined(),
    );
    const copied = window.location.search;
    expect(copied).toBe("?genebank=1&tab=prioriteringar");
    cleanup();

    open(copied, { is_manager: [1, 2], is_admin: false });
    expect(screen.getByText("Avelsprioritet visas")).toBeDefined();
    expect(window.location.search).toBe(copied);
  });

  it("replaces a genebank the user cannot open with the first one they can", async () => {
    open("?genebank=2");
    const entries = window.history.length;
    expect(screen.getByText("Översikt för genbank 1")).toBeDefined();
    await waitFor(() => expect(window.location.search).toBe("?genebank=1"));
    expect(window.history.length).toBe(entries); // replaced: Back does not return to it
    cleanup();

    open("?genebank=1", { is_manager: [], is_admin: false });
    expect(screen.getByText(/Välj en genbank/)).toBeDefined();
    await waitFor(() => expect(window.location.search).toBe(""));
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

  it("starts Avelsprioritet afresh for another genebank, so no message stays behind", () => {
    open("?genebank=1&tab=prioriteringar", { is_manager: [], is_admin: true });
    const first = screen.getByText("Avelsprioritet visas").dataset.mount;
    fireEvent.mouseDown(screen.getByRole("combobox"));
    fireEvent.click(
      within(screen.getByRole("listbox")).getByText("Mellerudskanin"),
    );
    expect(screen.getByText("Avelsprioritet visas").dataset.mount).not.toBe(
      first,
    );
  });
});
