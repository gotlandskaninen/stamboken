// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

const { showSnackbarMock, addNotificationMock } = vi.hoisted(() => ({
  showSnackbarMock: vi.fn(),
  addNotificationMock: vi.fn(),
}));

vi.mock("@/app/(app)/medlem/matrikel/actions", () => ({
  addPerson: vi.fn(),
  anonymizePerson: vi.fn(),
  createGrant: vi.fn(),
  linkPersonUser: vi.fn(),
  removePerson: vi.fn(),
  renewGrant: vi.fn(),
  revokeGrant: vi.fn(),
  setMainMember: vi.fn(),
  unlinkPersonUser: vi.fn(),
  updatePerson: vi.fn(),
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: showSnackbarMock }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification: addNotificationMock }),
}));

import { PersonsCard } from "@/app/(app)/medlem/matrikel/[id]/PersonsCard";
import type {
  MembershipDetail,
  Person,
} from "@/app/(app)/medlem/matrikel/types";

function person(over: Partial<Person> & Pick<Person, "id">): Person {
  return {
    first_name: "F",
    last_name: "L",
    email: "person@example.com",
    phone: null,
    role: "familjemedlem",
    end_date: null,
    user_id: null,
    user: null,
    grants: [],
    ...over,
  };
}

const MEMBERSHIP: MembershipDetail = {
  id: 1,
  member_number: 1274,
  membership_status: "active",
  address: null,
  postal_code: null,
  city: null,
  postal_address: null,
  billing_name: null,
  billing_address: null,
  billing_postal_code: null,
  billing_city: null,
  billing_email: null,
  billing_reference: null,
  publication_consent: {},
  payment_note: null,
  joined_date: "2019-03-01",
  notes: null,
  herds: [{ id: 3, herd: "G1274", herd_name: "Solhaga" }],
  persons: [
    person({
      id: 11,
      first_name: "Anna",
      last_name: "Linkad",
      role: "huvudmedlem",
      user_id: 7,
      user: { id: 7, username: "anna.l", email: "anna@example.com" },
    }),
    person({ id: 12, first_name: "Bo", last_name: "Olinkad" }),
    person({
      id: 13,
      first_name: "Cecilia",
      last_name: "Avslutad",
      role: "skotare",
      end_date: "2026-01-01",
      user_id: 8,
      user: { id: 8, username: "cecilia.a", email: "cecilia@example.com" },
    }),
    person({
      id: 14,
      first_name: "David",
      last_name: "Avslutad",
      end_date: "2026-01-01",
    }),
  ],
};

const row = (name: RegExp) => screen.getByRole("row", { name });

afterEach(cleanup);

describe("PersonsCard — Konto column", () => {
  it("shows the username and Koppla bort for a linked active person", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit />);
    const cell = row(/Anna Linkad/);
    expect(within(cell).getByText("anna.l")).toBeInTheDocument();
    expect(
      within(cell).getByRole("button", { name: "Koppla bort" }),
    ).toBeInTheDocument();
    expect(
      within(cell).queryByRole("button", { name: "Koppla konto…" }),
    ).not.toBeInTheDocument();
  });

  it("offers Koppla konto… for an unlinked active person", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit />);
    const cell = row(/Bo Olinkad/);
    expect(
      within(cell).getByRole("button", { name: "Koppla konto…" }),
    ).toBeInTheDocument();
  });

  it("keeps Koppla bort — but never Koppla konto… — on an ended linked person", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit />);
    const cell = row(/Cecilia Avslutad/);
    expect(within(cell).getByText("cecilia.a")).toBeInTheDocument();
    expect(
      within(cell).getByRole("button", { name: "Koppla bort" }),
    ).toBeInTheDocument();
    expect(
      within(cell).queryByRole("button", { name: "Koppla konto…" }),
    ).not.toBeInTheDocument();
  });

  it("renders an em dash for an ended unlinked person", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit />);
    const cell = row(/David Avslutad/);
    expect(within(cell).getByText("—")).toBeInTheDocument();
    expect(
      within(cell).queryByRole("button", { name: "Koppla konto…" }),
    ).not.toBeInTheDocument();
  });

  it("renders the column read-only when canEdit is false", () => {
    render(<PersonsCard membership={MEMBERSHIP} canEdit={false} />);
    expect(screen.getByText("Konto")).toBeInTheDocument();
    expect(screen.getByText("anna.l")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Koppla bort" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Koppla konto…" }),
    ).not.toBeInTheDocument();
  });
});
