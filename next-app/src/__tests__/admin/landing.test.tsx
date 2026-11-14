import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
// jest-dom matchers on vitest's expect (this project has no global setup —
// each render test registers them, matching DemoBanner.test.tsx).
import "@testing-library/jest-dom/vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { NAV_CONFIG } from "@/app/(app)/stamboken/(dashboard)/admin/_components/navConfig";
import type { UserContext } from "@/lib/user-context";

const { getUserMock, fetchApiMock } = vi.hoisted(() => ({
  getUserMock: vi.fn(),
  fetchApiMock: vi.fn(),
}));

vi.mock("@/lib/auth", () => ({ getUser: getUserMock }));
vi.mock("@/lib/api", () => ({ fetchApi: fetchApiMock }));

import AdminLandingPage from "@/app/(app)/stamboken/(dashboard)/admin/page";

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

// One card per nav GROUP the user can access — expected/hidden sets
// are derived from navConfig, not hardcoded, so the two stay in sync.
const CARD_TITLES: Record<string, string> = {
  ANVÄNDARE: "Användare",
  BESÄTTNINGAR: "Besättningar",
  GENBANKER: "Genbanker",
  UTSKICK: "Utskick",
  SYSTEM: "System",
};

const expectedTitles = (user: UserContext) =>
  NAV_CONFIG.filter((g) => g.items.some((i) => i.show({ user }))).map(
    (g) => CARD_TITLES[g.label],
  );

const hiddenTitles = (user: UserContext) =>
  Object.values(CARD_TITLES).filter((t) => !expectedTitles(user).includes(t));

describe("AdminLandingPage", () => {
  beforeEach(() => {
    getUserMock.mockReset();
    fetchApiMock.mockReset();
    // No backend in unit tests — counts degrade to count-less cards.
    fetchApiMock.mockRejectedValue(new Error("no backend"));
  });

  // No `globals: true` in vitest.config, so RTL's auto-cleanup afterEach never
  // registers — unmount manually or rendered DOM leaks across tests (matches
  // DemoBanner.test.tsx).
  afterEach(() => {
    cleanup();
  });

  it("admin sees a card for every nav group", async () => {
    const admin = makeUser({ is_admin: true });
    getUserMock.mockResolvedValue(admin);
    render(await AdminLandingPage());
    expect(expectedTitles(admin)).toHaveLength(5); // all groups visible
    for (const title of expectedTitles(admin)) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
  });

  // Medlemsregistret är ett utlänkskort utanför NAV_CONFIG (navConfig.
  // isMemberAdmin): admin, genbanksansvarig och matrikeladmin ser det.
  it("matrikel admin sees only the Medlemsregister card", async () => {
    const matrikel = makeUser({ is_matrikel_admin: true });
    getUserMock.mockResolvedValue(matrikel);
    render(await AdminLandingPage());
    expect(
      screen.getByRole("heading", { name: "Medlemsregister" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /Medlemsregister/ }),
    ).toHaveAttribute("href", "/medlem/matrikel");
    for (const title of Object.values(CARD_TITLES)) {
      expect(screen.queryByRole("heading", { name: title })).toBeNull();
    }
  });

  it("owner-only user gets no Medlemsregister card", async () => {
    getUserMock.mockResolvedValue(makeUser({ is_owner: ["G1"] }));
    render(await AdminLandingPage());
    expect(
      screen.queryByRole("heading", { name: "Medlemsregister" }),
    ).toBeNull();
  });

  it("manager sees only their groups' cards", async () => {
    const manager = makeUser({ is_manager: [1] });
    getUserMock.mockResolvedValue(manager);
    render(await AdminLandingPage());
    for (const title of expectedTitles(manager)) {
      expect(screen.getByRole("heading", { name: title })).toBeInTheDocument();
    }
    for (const title of hiddenTitles(manager)) {
      expect(screen.queryByRole("heading", { name: title })).toBeNull();
    }
    expect(
      screen.getByRole("heading", { name: "Medlemsregister" }),
    ).toBeInTheDocument();
  });
});
