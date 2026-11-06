import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { NAV_ITEMS } from "@/components/shell/nav-items";
import { TopbarNav } from "@/components/shell/TopbarNav";

let pathname = "/stamboken/min-besattning";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

beforeAll(async () => {
  await import("@/i18n");
});

afterEach(() => {
  pathname = "/stamboken/min-besattning";
  cleanup();
});

describe("TopbarNav", () => {
  it("exports exactly the five breeder dashboard destinations in order", () => {
    expect(NAV_ITEMS.map((item) => item.href)).toEqual([
      "/stamboken/min-besattning",
      "/stamboken/alla-kaniner",
      "/stamboken/genetik",
      "/stamboken/provparning",
      "/stamboken/profil",
    ]);
    expect(NAV_ITEMS.map((item) => item.i18nKey)).toEqual([
      "sidebar.minBesattning",
      "sidebar.allaKaniner",
      "sidebar.genetik",
      "sidebar.provparning",
      "sidebar.profil",
    ]);
  });

  it("keeps template demo and role-gated destinations out of breeder navigation", () => {
    const demoKeys = [
      "dashboard",
      "projects",
      "orders",
      "invoices",
      "calendar",
      "documentation",
    ];

    expect(NAV_ITEMS.map((item) => item.key)).not.toEqual(
      expect.arrayContaining(demoKeys),
    );
    expect(NAV_ITEMS.every((item) => !item.href.startsWith("/medlem"))).toBe(
      true,
    );
    expect(
      NAV_ITEMS.every((item) => !item.href.toLowerCase().includes("admin")),
    ).toBe(true);
  });

  it("renders the five Swedish dashboard links in navigation order", () => {
    render(<TopbarNav />);

    const navigation = screen.getByRole("navigation", {
      name: "Huvudmeny",
    });

    expect(
      within(navigation)
        .getAllByRole("link")
        .map((link) => ({
          name: link.textContent,
          href: link.getAttribute("href"),
        })),
    ).toEqual([
      { name: "Min besättning", href: "/stamboken/min-besattning" },
      { name: "Alla kaniner", href: "/stamboken/alla-kaniner" },
      { name: "Genetik", href: "/stamboken/genetik" },
      { name: "Provparning", href: "/stamboken/provparning" },
      { name: "Profil", href: "/stamboken/profil" },
    ]);
  });

  it("marks the current dashboard link as the active page", () => {
    pathname = "/stamboken/genetik";

    render(<TopbarNav />);

    expect(screen.getByRole("link", { name: "Genetik" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("keeps a dashboard link active on its nested routes", () => {
    pathname = "/stamboken/genetik/arsrapport";

    render(<TopbarNav />);

    expect(screen.getByRole("link", { name: "Genetik" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });
});
