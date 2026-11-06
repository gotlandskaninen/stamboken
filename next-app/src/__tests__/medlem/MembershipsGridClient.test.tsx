// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import {
  afterEach,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const { pushMock } = vi.hoisted(() => ({ pushMock: vi.fn() }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));

import { MembershipsGridClient } from "@/app/(app)/medlem/matrikel/MembershipsGridClient";
import type { MembershipRow } from "@/app/(app)/medlem/matrikel/types";

// MUI X DataGrid measures its container; jsdom reports 0×0 and would render no
// rows at all without these two stubs.
beforeAll(() => {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
  Object.defineProperty(HTMLElement.prototype, "getBoundingClientRect", {
    configurable: true,
    value: () => ({
      width: 900,
      height: 600,
      top: 0,
      left: 0,
      right: 900,
      bottom: 600,
      x: 0,
      y: 0,
      toJSON: () => {},
    }),
  });
});

const rows: MembershipRow[] = [
  {
    id: 11,
    member_number: 101,
    membership_status: "active",
    main_first_name: "Anna",
    main_last_name: "Lindqvist",
    main_email: "anna@example.com",
    main_phone: null,
    address: "Gatan 1",
    postal_code: "623 55",
    city: "Visby",
    postal_address: "623 55 Visby",
    persons: [
      {
        id: 1,
        first_name: "Anna",
        last_name: "Lindqvist",
        role: "huvudmedlem",
        end_date: null,
      },
      {
        id: 2,
        first_name: "Bo",
        last_name: "Lindqvist",
        role: "familjemedlem",
        end_date: null,
      },
      {
        id: 3,
        first_name: "Cecilia",
        last_name: "Lindqvist",
        role: "skotare",
        end_date: "2025-01-01",
      },
    ],
  },
  {
    id: 12,
    member_number: 102,
    membership_status: "pending",
    main_first_name: "Bertil",
    main_last_name: "Ek",
    main_email: null,
    main_phone: "070-1234567",
    address: null,
    postal_code: null,
    city: null,
    postal_address: null,
    persons: [],
  },
  {
    id: 13,
    member_number: null,
    membership_status: "friexemplar",
    main_first_name: "Cecilia",
    main_last_name: "Sund",
    main_email: "cecilia@example.com",
    main_phone: null,
    address: null,
    postal_code: "621 41",
    city: "Visby",
    postal_address: "621 41 Visby",
    persons: [
      {
        id: 4,
        first_name: "Cecilia",
        last_name: "Sund",
        role: "huvudmedlem",
        end_date: null,
      },
    ],
  },
];

beforeEach(() => {
  pushMock.mockReset();
});

afterEach(cleanup);

describe("MembershipsGridClient", () => {
  it("renders one row per membership with status label, huvudmedlem, address and active person count", () => {
    render(<MembershipsGridClient rows={rows} total={3} />);

    expect(screen.getAllByRole("row")).toHaveLength(4); // header + 3
    expect(screen.getByText("Anna Lindqvist")).toBeInTheDocument();
    expect(screen.getByText("Bertil Ek")).toBeInTheDocument();
    expect(screen.getByText("Cecilia Sund")).toBeInTheDocument();

    // STATUS_LABELS, not the raw backend value
    expect(screen.getByText("Aktiv")).toBeInTheDocument();
    expect(screen.getByText("Väntar")).toBeInTheDocument();
    expect(screen.getByText("Friexemplar")).toBeInTheDocument();

    // address + the backend-derived postal_address
    expect(screen.getByText("Gatan 1, 623 55 Visby")).toBeInTheDocument();
    expect(screen.getByText("621 41 Visby")).toBeInTheDocument();

    // kontakt falls back from e-post to telefon
    expect(screen.getByText("anna@example.com")).toBeInTheDocument();
    expect(screen.getByText("070-1234567")).toBeInTheDocument();

    // active persons only (Cecilia has an end_date)
    expect(screen.getByText("2")).toBeInTheDocument();
  });

  it("navigates to the membership detail page on row click", () => {
    render(<MembershipsGridClient rows={rows} total={3} />);
    fireEvent.click(screen.getByText("Bertil Ek"));
    expect(pushMock).toHaveBeenCalledWith("/medlem/matrikel/12");
  });

  it("shows the empty state when nothing matches", () => {
    render(<MembershipsGridClient rows={[]} total={0} />);
    expect(screen.getByText("Inga medlemskap matchar.")).toBeInTheDocument();
  });
});
