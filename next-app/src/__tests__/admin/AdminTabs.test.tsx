import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import { AdminTabs } from "@/app/(app)/stamboken/(dashboard)/admin/_components/AdminTabs";
import type { UserContext } from "@/lib/user-context";

let pathname = "/stamboken/admin";

vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
}));

function makeUser(overrides: Partial<UserContext>): UserContext {
  return {
    id: 1,
    email: "test@example.com",
    fullname: null,
    username: "testuser",
    validated: false,
    is_admin: false,
    is_manager: null,
    is_owner: null,
    is_matrikel_admin: false,
    profile_picture: null,
    google_picture: null,
    google_name: null,
    google_email: null,
    use_google_picture: false,
    v2_prod_access: false,
    ...overrides,
  };
}

// Inget globals: true i vitest.config.ts → RTL:s auto-cleanup registreras
// aldrig; städa manuellt (samma mönster som landing.test.tsx:65-70).
afterEach(() => {
  pathname = "/stamboken/admin";
  cleanup();
});

describe("AdminTabs (ersätter den gamla sidomenyn)", () => {
  it("renderar en flik per synlig navgrupp för en administratör", () => {
    render(<AdminTabs user={makeUser({ is_admin: true })} />);
    const nav = screen.getByRole("navigation", {
      name: "Adminpanelens avsnitt",
    });
    expect(
      within(nav)
        .getAllByRole("tab")
        .map((tab) => ({
          name: tab.textContent,
          href: tab.getAttribute("href"),
        })),
    ).toEqual([
      { name: "Översikt", href: "/stamboken/admin" },
      { name: "Användare", href: "/stamboken/admin/anvandare" },
      { name: "Besättningar", href: "/stamboken/admin/besattningar" },
      { name: "Genbanker", href: "/stamboken/admin/genbanker" },
      { name: "Utskick", href: "/stamboken/admin/utskick" },
      { name: "System", href: "/stamboken/admin/system/online" },
    ]);
  });

  it("skalar ned för genbanksansvarig och behåller genbanksetiketten", () => {
    // Etiketten som e2e/admin/03-manager-scoped-view.spec.ts:29 låser.
    render(
      <AdminTabs
        user={makeUser({ is_manager: [1] })}
        gbNames={["Gotlandskanin"]}
      />,
    );
    expect(screen.getAllByRole("tab").map((tab) => tab.textContent)).toEqual([
      "Översikt",
      "Besättningar i Gotlandskanin",
      "Genbanker",
      "Utskick",
    ]);
  });

  it("markerar sektionsfliken aktiv även på nästlade rutter", () => {
    pathname = "/stamboken/admin/system/audit";
    render(<AdminTabs user={makeUser({ is_admin: true })} />);
    expect(screen.getByRole("tab", { name: "System" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("tab", { name: "Översikt" })).not.toHaveAttribute(
      "aria-current",
    );
  });
});
