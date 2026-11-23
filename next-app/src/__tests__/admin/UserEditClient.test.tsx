import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

const revokeRole = vi.hoisted(() => vi.fn());
const logoutEverywhere = vi.hoisted(() => vi.fn());
const removeGoogleLogin = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/admin/anvandare/actions", () => ({
  grantRole: vi.fn(),
  logoutEverywhere,
  removeGoogleLogin,
  resetPassword: vi.fn(),
  revokeRole,
  setAccountActive: vi.fn(),
  setValidated: vi.fn(),
  setV2ProdAccess: vi.fn(),
  updateUserProfile: vi.fn(),
}));

import { resetPassword } from "@/app/(app)/stamboken/(dashboard)/admin/anvandare/actions";
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

  it("hides the newly issued password from the Tyck till picture", async () => {
    vi.mocked(resetPassword).mockResolvedValue({ plaintext: "nytt-hemligt" });
    render(
      <UserEditClient
        detail={detail}
        actorId={1}
        genebanks={[]}
        herds={[]}
        recentAudit={[]}
        concurrentEditWarning={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Återställ lösenord" }));
    const code = await waitFor(() => screen.getByText("nytt-hemligt"));
    expect(code.closest('[data-tyck-till="dolj"]')).not.toBeNull();
  });
});

describe("UserEditClient sessions", () => {
  // The admin's own page: the dialog says she is logged out too.
  const openLogoutDialog = () => {
    render(
      <UserEditClient
        detail={detail}
        actorId={7}
        genebanks={[]}
        herds={[]}
        recentAudit={[]}
        concurrentEditWarning={null}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Logga ut överallt" }));
    return screen.getByRole("dialog");
  };

  it("asks first, and Avbryt logs nobody out", () => {
    logoutEverywhere.mockClear();
    const dialog = openLogoutDialog();
    expect(logoutEverywhere).not.toHaveBeenCalled();
    expect(dialog).toHaveTextContent("du loggas också ut här");
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    expect(logoutEverywhere).not.toHaveBeenCalled();
  });

  it("logs the account out everywhere once the admin confirms", () => {
    logoutEverywhere.mockClear();
    const dialog = openLogoutDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Logga ut" }));
    expect(logoutEverywhere).toHaveBeenCalledWith(7);
  });
});

describe("UserEditClient Google login", () => {
  const openGoogleDialog = () => {
    render(
      <UserEditClient
        detail={detail}
        actorId={1}
        genebanks={[]}
        herds={[]}
        recentAudit={[]}
        concurrentEditWarning={null}
      />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Ta bort Google-inloggningen" }),
    );
    return screen.getByRole("dialog");
  };

  it("asks first, and Avbryt removes nothing", () => {
    removeGoogleLogin.mockClear();
    const dialog = openGoogleDialog();
    expect(dialog).toHaveTextContent("Ta bort Google-inloggningen?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    expect(removeGoogleLogin).not.toHaveBeenCalled();
  });

  it("removes the Google login once the admin confirms", () => {
    removeGoogleLogin.mockClear();
    const dialog = openGoogleDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort" }));
    expect(removeGoogleLogin).toHaveBeenCalledWith(7);
  });
});
