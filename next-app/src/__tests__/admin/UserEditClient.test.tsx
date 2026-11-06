import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const revokeRole = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/admin/anvandare/actions", () => ({
  grantRole: vi.fn(),
  resetPassword: vi.fn(),
  revokeRole,
  setAccountActive: vi.fn(),
  setValidated: vi.fn(),
  setV2ProdAccess: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { UserEditClient } from "@/app/(app)/stamboken/(dashboard)/admin/anvandare/[userId]/UserEditClient";
import type { AdminUserDetail } from "@/app/(app)/stamboken/(dashboard)/admin/_lib/types";

afterEach(cleanup);

const detail: AdminUserDetail = {
  id: 7,
  uuid: "u-7",
  username: "matr",
  email: "matr@example.org",
  fullname: "Mats Matrikel",
  role_summary: "matrikel_admin",
  validated: true,
  v2_prod_access: false,
  is_active: true,
  last_active: null,
  google_linked: false,
  _privileges: [{ level: "matrikel_admin" }],
  profile_picture: null,
  google_picture: null,
  google_name: null,
  google_email: null,
  use_google_picture: false,
};

describe("UserEditClient roles", () => {
  it("shows a matrikel_admin entry by name, without a target, and revokes it as sent", () => {
    render(
      <UserEditClient
        detail={detail}
        actorId={1}
        genebanks={[{ id: 1, name: "Gotlandskaninen" }]}
        herds={[]}
        recentAudit={[]}
        concurrentEditWarning={null}
      />,
    );
    expect(screen.getByText("Matrikeladministratör")).toBeInTheDocument();
    expect(screen.queryByText(/genbank undefined/)).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "Ta bort Matrikeladministratör" }),
    );
    expect(revokeRole).toHaveBeenCalledWith(7, { level: "matrikel_admin" });
  });
});
