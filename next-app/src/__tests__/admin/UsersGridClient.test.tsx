import "@testing-library/jest-dom/vitest";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import {
  UsersGridClient,
  type UserRow,
} from "@/app/(app)/stamboken/(dashboard)/admin/anvandare/UsersGridClient";

// MUI X DataGrid measures its container; jsdom reports 0×0 (same stubs as
// MembershipsGridClient.test.tsx).
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      width: 1400,
      height: 600,
      top: 0,
      left: 0,
      right: 1400,
      bottom: 600,
      x: 0,
      y: 0,
      toJSON: () => {},
    }),
  });
});

afterEach(cleanup);

const base: UserRow = {
  id: 174,
  username: null,
  fullname: null,
  email: "konto@example.org",
  roleLabel: "Besättningsägare (1 besättningar)",
  last_active: "aldrig",
  validated: false,
  v2_prod_access: false,
  is_active: true,
  google_linked: true,
};

describe("UsersGridClient", () => {
  it("shows the account number and flags a role holder without a name (#192)", () => {
    render(
      <UsersGridClient
        rows={[base, { ...base, id: 175, roleLabel: "Ingen roll" }]}
        total={2}
        query=""
        sortField="last_active"
        sortDir="desc"
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Nr" })).toBeVisible();
    expect(screen.getByText("174")).toBeInTheDocument();
    expect(screen.getByText("175")).toBeInTheDocument();
    expect(screen.getAllByText("Namn saknas")).toHaveLength(1);
  });
});
