import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { UserContext } from "@/lib/user-context";
import { AvatarMenu } from "@/components/shell/AvatarMenu";

const mocks = vi.hoisted(() => ({
  user: null as UserContext | null,
  mode: "demo",
  pendingCount: 0,
  hasAnyVisible: vi.fn(),
  dispatch: vi.fn(),
  push: vi.fn(),
  refresh: vi.fn(),
  logout: vi.fn(async () => undefined),
  setMode: vi.fn(async () => undefined),
  resetApiState: vi.fn(() => ({ type: "api/resetApiState" })),
}));

vi.mock("@/lib/user-context", () => ({
  useUser: () => mocks.user,
}));

vi.mock("@/lib/mode-context", () => ({
  useMode: () => mocks.mode,
}));

vi.mock(
  "@/app/(app)/stamboken/(dashboard)/admin/_components/navConfig",
  async (importOriginal) => ({
    // isMemberAdmin stays real — the medlem-menu tests toggle the flags.
    ...(await importOriginal<
      typeof import("@/app/(app)/stamboken/(dashboard)/admin/_components/navConfig")
    >()),
    hasAnyVisible: mocks.hasAnyVisible,
  }),
);

vi.mock("@/redux/api/memberApplicationsEndpoints", () => ({
  usePendingMemberApplicationCountQuery: () => ({
    data: { pending: mocks.pendingCount },
  }),
}));

vi.mock("@/redux/api/apiSlice", () => ({
  apiSlice: {
    util: {
      resetApiState: mocks.resetApiState,
    },
  },
}));

vi.mock("@/hooks/useAppDispatch", () => ({
  useAppDispatch: () => mocks.dispatch,
}));

vi.mock("@/app/(app)/(auth)/actions", () => ({
  logout: mocks.logout,
  setMode: mocks.setMode,
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: mocks.push,
    refresh: mocks.refresh,
  }),
}));

function userFixture(overrides: Partial<UserContext> = {}): UserContext {
  return {
    id: 1,
    email: "owner@example.test",
    fullname: "Test Owner",
    username: "owner",
    validated: true,
    is_admin: false,
    is_manager: null,
    is_owner: ["G1274"],
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

function openMenu() {
  render(<AvatarMenu />);
  fireEvent.click(screen.getByRole("button", { name: "Account" }));
}

function expectMemberItems() {
  expect(screen.getByText("Medlemsansökningar")).toBeInTheDocument();
  expect(screen.getByText("Matrikel")).toBeInTheDocument();
  expect(screen.getByText("Statistik")).toBeInTheDocument();
}

function expectNoMemberItems() {
  expect(screen.queryByText("Medlemsansökningar")).not.toBeInTheDocument();
  expect(screen.queryByText("Matrikel")).not.toBeInTheDocument();
  expect(screen.queryByText("Statistik")).not.toBeInTheDocument();
}

afterEach(() => {
  cleanup();
});

beforeEach(() => {
  vi.clearAllMocks();
  mocks.user = userFixture();
  mocks.mode = "demo";
  mocks.pendingCount = 0;
  mocks.hasAnyVisible.mockReturnValue(false);
});

describe("AvatarMenu", () => {
  it("shows Adminpanel exactly when hasAnyVisible permits it", () => {
    mocks.user = userFixture({ is_admin: true });
    mocks.hasAnyVisible.mockReturnValue(false);

    openMenu();

    expect(screen.queryByText("Adminpanel")).not.toBeInTheDocument();
    expect(mocks.hasAnyVisible).toHaveBeenCalledWith(mocks.user);

    cleanup();
    mocks.user = userFixture();
    mocks.hasAnyVisible.mockReturnValue(true);

    openMenu();

    expect(screen.getByText("Adminpanel")).toBeInTheDocument();
    expect(mocks.hasAnyVisible).toHaveBeenLastCalledWith(mocks.user);
  });

  it("shows member administration items for an admin", () => {
    mocks.user = userFixture({ is_admin: true });

    openMenu();

    expectMemberItems();
  });

  it("shows member administration items for a genebank manager", () => {
    mocks.user = userFixture({ is_manager: [1] });

    openMenu();

    expectMemberItems();
  });

  it("shows member administration items for a matrikel admin", () => {
    mocks.user = userFixture({ is_matrikel_admin: true });

    openMenu();

    expectMemberItems();
  });

  it("hides Adminpanel and member administration items for a plain owner", () => {
    openMenu();

    expect(screen.queryByText("Adminpanel")).not.toBeInTheDocument();
    expectNoMemberItems();
    expect(screen.getByText("Logga ut")).toBeInTheDocument();
  });

  it("renders the pending member application count", () => {
    mocks.user = userFixture({ is_admin: true });
    mocks.pendingCount = 3;

    openMenu();

    expect(screen.getByText("Medlemsansökningar (3)")).toBeInTheDocument();
  });

  it("shows the mode toggle only for users with production access", () => {
    mocks.user = userFixture({ v2_prod_access: true });

    openMenu();

    expect(
      screen.getByRole("menuitem", {
        name: /Byt till (testmiljön|riktiga stamboken)/,
      }),
    ).toBeInTheDocument();

    cleanup();
    mocks.user = userFixture({ v2_prod_access: false });

    openMenu();

    expect(
      screen.queryByRole("menuitem", {
        name: /Byt till (testmiljön|riktiga stamboken)/,
      }),
    ).not.toBeInTheDocument();
  });
});
