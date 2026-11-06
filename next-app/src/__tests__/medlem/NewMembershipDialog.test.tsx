// jest-dom matchers on vitest's expect (this project has no global setup —
// see src/__tests__/admin/landing.test.tsx).
import "@testing-library/jest-dom/vitest";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const {
  pushMock,
  createMembershipMock,
  showSnackbarMock,
  addNotificationMock,
} = vi.hoisted(() => ({
  pushMock: vi.fn(),
  createMembershipMock: vi.fn(),
  showSnackbarMock: vi.fn(),
  addNotificationMock: vi.fn(),
}));

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: pushMock }) }));
vi.mock("@/app/(app)/medlem/matrikel/actions", () => ({
  createMembership: createMembershipMock,
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar: showSnackbarMock }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification: addNotificationMock }),
}));

import {
  NewMembershipButton,
  NewMembershipDialog,
} from "@/app/(app)/medlem/matrikel/NewMembershipDialog";

beforeEach(() => {
  pushMock.mockReset();
  createMembershipMock.mockReset();
  showSnackbarMock.mockReset();
  addNotificationMock.mockReset();
  createMembershipMock.mockResolvedValue({ ok: true, id: 77 });
});

afterEach(cleanup);

// Required TextFields render their label as "Förnamn *" — anchor instead of
// matching the whole string. (A function matcher rather than
// `new RegExp(label)`: Semgrep's detect-non-literal-regexp gate flags that.)
const field = (label: string) =>
  screen.getByLabelText((content) => content.startsWith(label));

function fill(label: string, value: string) {
  fireEvent.change(field(label), { target: { value } });
}

describe("NewMembershipDialog", () => {
  it("sends the address trio and navigates to the new membership", async () => {
    render(<NewMembershipDialog open onClose={() => {}} />);

    fill("Förnamn", "Ny");
    fill("Efternamn", "Medlem");
    fill("Gatuadress", "Gatan 1");
    fill("Postnummer", "62355");
    fireEvent.blur(field("Postnummer"));
    fill("Postort", "Visby");

    // blur normalises 62355 -> "623 55" before the action is called
    expect(field("Postnummer")).toHaveValue("623 55");

    fireEvent.click(screen.getByRole("button", { name: "Skapa" }));

    await waitFor(() => expect(createMembershipMock).toHaveBeenCalledTimes(1));
    expect(createMembershipMock).toHaveBeenCalledWith(
      expect.objectContaining({
        first_name: "Ny",
        last_name: "Medlem",
        address: "Gatan 1",
        postal_code: "623 55",
        city: "Visby",
      }),
    );
    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith("/medlem/matrikel/77"),
    );
  });

  it("reports a failed create through the snackbar and notifications", async () => {
    createMembershipMock.mockResolvedValue({
      ok: false,
      error: "Medlemsnumret är upptaget",
    });
    const onClose = vi.fn();
    render(<NewMembershipDialog open onClose={onClose} />);

    fill("Förnamn", "Ny");
    fill("Efternamn", "Medlem");
    fireEvent.click(screen.getByRole("button", { name: "Skapa" }));

    await waitFor(() =>
      expect(showSnackbarMock).toHaveBeenCalledWith(
        "Medlemsnumret är upptaget",
        "error",
      ),
    );
    expect(addNotificationMock).toHaveBeenCalledWith({
      title: "Kunde inte skapa medlemskap",
      message: "Medlemsnumret är upptaget",
      type: "error",
    });
    // The dialog stays open with the typed values intact, and nothing navigates.
    expect(onClose).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(field("Förnamn")).toHaveValue("Ny");
  });

  it("blocks an invalid postnummer", () => {
    render(<NewMembershipDialog open onClose={() => {}} />);

    fill("Förnamn", "Ny");
    fill("Efternamn", "Medlem");
    fill("Postnummer", "62");

    expect(
      screen.getByText("Postnummer ska vara fem siffror"),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Skapa" })).toBeDisabled();
  });
});

describe("NewMembershipButton", () => {
  it("forgets a cancelled draft when the dialog is opened again", async () => {
    render(<NewMembershipButton />);
    const openBtn = () =>
      screen.getByRole("button", { name: "Nytt medlemskap" });

    fireEvent.click(openBtn());
    fill("Förnamn", "Halvfärdig");
    expect(field("Förnamn")).toHaveValue("Halvfärdig");

    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    await waitFor(() =>
      expect(screen.queryByLabelText(/^Förnamn/)).not.toBeInTheDocument(),
    );

    fireEvent.click(openBtn());
    expect(field("Förnamn")).toHaveValue("");
  });
});
