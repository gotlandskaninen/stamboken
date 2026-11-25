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
const setAccountActive = vi.hoisted(() => vi.fn());
const setV2ProdAccess = vi.hoisted(() => vi.fn());
const eraseAccount = vi.hoisted(() => vi.fn());
const updateUserProfile = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn() }),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/admin/anvandare/actions", () => ({
  eraseAccount,
  grantRole: vi.fn(),
  logoutEverywhere,
  removeGoogleLogin,
  resetPassword: vi.fn(),
  revokeRole,
  setAccountActive,
  setValidated: vi.fn(),
  setV2ProdAccess,
  updateUserProfile,
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

  it("shows each owned herd's status in words and links it to the herd page (#214)", () => {
    render(
      <UserEditClient
        detail={{
          ...detail,
          _privileges: [
            { level: "owner", herd: 1 },
            { level: "owner", herd: 2 },
          ],
        }}
        actorId={1}
        genebanks={[]}
        herds={[
          { id: 1, herd: "G9001", herd_name: "Exempelgården", is_active: true },
          { id: 2, herd: "M9002", herd_name: null, is_active: false },
        ]}
        recentAudit={[]}
        concurrentEditWarning={null}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(
      within(rows[0]).getByRole("link", { name: "G9001 — Exempelgården" }),
    ).toHaveAttribute("href", "/stamboken/admin/besattningar/G9001");
    expect(within(rows[0]).getByText("Aktiv")).toBeInTheDocument();
    expect(
      within(rows[1]).getByRole("link", { name: "M9002" }),
    ).toHaveAttribute("href", "/stamboken/admin/besattningar/M9002");
    expect(within(rows[1]).getByText("Inaktiv")).toBeInTheDocument();
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

describe("UserEditClient switches (#249)", () => {
  const renderPage = () =>
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

  it("saves the real-stambok switch and confirms it on the page", async () => {
    setV2ProdAccess.mockResolvedValue(undefined);
    renderPage();
    expect(screen.queryByText("Ändringen är sparad.")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("switch", { name: /riktiga stamboken/ }));
    expect(setV2ProdAccess).toHaveBeenCalledWith(7, true);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Ändringen är sparad.",
    );
  });

  it("asks before deactivating, then confirms the change on the page", async () => {
    setAccountActive.mockResolvedValue(undefined);
    renderPage();
    fireEvent.click(screen.getByRole("switch", { name: "Kontot är aktivt" }));
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Inaktivera" }));
    expect(setAccountActive).toHaveBeenCalledWith(7, false);
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Ändringen är sparad.",
    );
  });

  it("shows a refusal instead of the confirmation", async () => {
    setAccountActive.mockResolvedValue({ error: "Nej." });
    renderPage();
    fireEvent.click(screen.getByRole("switch", { name: "Kontot är aktivt" }));
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Inaktivera",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("Nej.");
    expect(screen.queryByText("Ändringen är sparad.")).not.toBeInTheDocument();
  });
});

describe("UserEditClient Radera kontots uppgifter (#250)", () => {
  // An account without a role, not the admin's own.
  const plain: AdminUserDetail = {
    ...detail,
    role_summary: "ingen roll",
    _privileges: [],
  };
  const renderPage = (d: AdminUserDetail, actorId = 1) =>
    render(
      <UserEditClient
        detail={d}
        actorId={actorId}
        genebanks={[]}
        herds={[]}
        recentAudit={[]}
        concurrentEditWarning={null}
      />,
    );
  const button = () =>
    screen.getByRole("button", { name: "Radera kontots uppgifter" });

  it("says it cannot be undone, and Avbryt erases nothing", () => {
    eraseAccount.mockClear();
    renderPage(plain);
    fireEvent.click(button());
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Det går inte att ångra.");
    expect(dialog).toHaveTextContent("raderad-7");
    fireEvent.click(within(dialog).getByRole("button", { name: "Avbryt" }));
    expect(eraseAccount).not.toHaveBeenCalled();
  });

  it("erases the account once the admin confirms", async () => {
    eraseAccount.mockClear();
    eraseAccount.mockResolvedValue(undefined);
    renderPage(plain);
    fireEvent.click(button());
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Radera",
      }),
    );
    expect(eraseAccount).toHaveBeenCalledWith(7);
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });

  it("is on for an account with only Läsrätt", () => {
    renderPage({
      ...plain,
      _privileges: [
        { level: "viewer", genebank: 1 },
        { level: "viewer", genebank: 2 },
      ],
    });
    expect(button()).toBeEnabled();
  });

  it("is off for an account with a role and for the admin's own", () => {
    renderPage(detail);
    expect(button()).toBeDisabled();
    cleanup();
    renderPage(plain, 7);
    expect(button()).toBeDisabled();
  });

  it("shows an erased account as erased, without the button", () => {
    renderPage({
      ...plain,
      username: null,
      fullname: null,
      email: "raderad-7",
      is_active: false,
    });
    expect(screen.getByText(/Kontots uppgifter är raderade/)).toHaveTextContent(
      "Raden finns kvar som raderad-7",
    );
    expect(
      screen.queryByRole("button", { name: "Radera kontots uppgifter" }),
    ).toBeNull();
  });
});

describe("UserEditClient profile form", () => {
  const props = {
    actorId: 1,
    genebanks: [],
    herds: [],
    recentAudit: [],
    concurrentEditWarning: null,
  };

  it("sends only what the admin changed, and keeps another admin's address after a refresh", async () => {
    updateUserProfile.mockClear();
    updateUserProfile.mockResolvedValue(undefined);
    const { rerender } = render(<UserEditClient detail={detail} {...props} />);
    expect(screen.getByRole("button", { name: "Spara" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Fullständigt namn"), {
      target: { value: "Nytt Namn" },
    });
    // Another admin changed the address; the page re-rendered with it.
    rerender(
      <UserEditClient
        detail={{ ...detail, email: "ny@example.org" }}
        {...props}
      />,
    );
    expect(screen.getByLabelText("E-post")).toHaveValue("ny@example.org");
    expect(screen.getByLabelText("Fullständigt namn")).toHaveValue("Nytt Namn");
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    expect(updateUserProfile).toHaveBeenCalledWith(7, {
      fullname: "Nytt Namn",
    });
    expect(await screen.findByRole("status")).toHaveTextContent(
      "Ändringen är sparad.",
    );
  });
});
