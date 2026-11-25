import "@testing-library/jest-dom/vitest";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import MembershipDetailPage from "@/app/(app)/medlem/matrikel/[id]/page";
import type { MembershipDetail } from "@/app/(app)/medlem/matrikel/types";

const { fetchApi, getUser } = vi.hoisted(() => ({
  fetchApi: vi.fn(),
  getUser: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ fetchApi }));
vi.mock("@/lib/auth", () => ({ getUser }));
vi.mock("@/app/(app)/medlem/matrikel/[id]/MembershipFormCard", () => ({
  MembershipFormCard: () => null,
}));
vi.mock("@/app/(app)/medlem/matrikel/[id]/PersonsCard", () => ({
  PersonsCard: () => null,
}));

const org: MembershipDetail = {
  id: 1,
  member_number: 123,
  membership_status: "active",
  organization_name: "Exempelföreningen",
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
  joined_date: null,
  notes: null,
  payment_note: null,
  publication_consent: {},
  persons: [],
  herds: [],
};

afterEach(cleanup);

it.each([true, false])(
  "shows the organisation in the heading and keeps four overview cells (admin=%s)",
  async (admin) => {
    fetchApi.mockResolvedValue(
      admin ? { ...org, organization_number: "123456-7897" } : org,
    );
    getUser.mockResolvedValue({ is_admin: admin });
    render(
      await MembershipDetailPage({ params: Promise.resolve({ id: "1" }) }),
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Exempelföreningen" }),
    ).toBeInTheDocument();
    const meta = screen.getByText(/Medlemskap nr 123/);
    expect(
      screen.getByRole("region", { name: "Översikt" }).children,
    ).toHaveLength(4);
    if (admin) {
      expect(meta).toHaveTextContent("123456-7897");
    } else {
      expect(screen.queryByText(/123456-7897/)).not.toBeInTheDocument();
    }
  },
);

it("shows each herd's own status and links the herds the reader may open (#214)", async () => {
  fetchApi.mockResolvedValue({
    ...org,
    herds: [
      {
        id: 3,
        herd: "G9001",
        herd_name: null,
        genebank_id: 1,
        is_active: true,
      },
      {
        id: 4,
        herd: "M9002",
        herd_name: null,
        genebank_id: 2,
        is_active: null,
      },
    ],
  });
  getUser.mockResolvedValue({ is_admin: false, is_manager: [1] });
  render(await MembershipDetailPage({ params: Promise.resolve({ id: "1" }) }));
  expect(screen.getByRole("link", { name: "G9001 · aktiv" })).toHaveAttribute(
    "href",
    "/stamboken/admin/besattningar/G9001",
  );
  expect(screen.getByText("M9002 · inaktiv")).not.toHaveAttribute("href");
  expect(screen.queryByRole("link", { name: /M9002/ })).toBeNull();
});
