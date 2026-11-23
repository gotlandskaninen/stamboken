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
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { UserProvider, type UserContext } from "@/lib/user-context";

const send = vi.fn();
vi.mock("../actions", () => ({
  sendTyckTill: (...a: unknown[]) => send(...a),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/stamboken/min-besattning",
}));

import { TyckTillDialog } from "../TyckTillDialog.client";

const member = { id: 1, email: "anna@exempel.se" } as UserContext;

// jsdom has no showModal.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
    this.dispatchEvent(new Event("close"));
  };
  window.matchMedia = ((q: string) => ({ matches: false, media: q })) as never;
  if (!globalThis.crypto.randomUUID)
    globalThis.crypto.randomUUID = () => "00000000-0000-4000-8000-000000000000";
});
beforeEach(() => send.mockReset());
afterEach(cleanup);

function ui(user: UserContext | null) {
  const dialog = <TyckTillDialog open onClose={() => {}} />;
  return user ? <UserProvider user={user}>{dialog}</UserProvider> : dialog;
}

describe("TyckTillDialog", () => {
  it("renders without a UserProvider and asks logged-out visitors for an address", () => {
    render(ui(null));
    expect(screen.getByLabelText("Din e-postadress")).toBeInTheDocument();
    expect(
      screen.queryByText("Vem får läsa det du skriver?"),
    ).not.toBeInTheDocument();
  });

  it("gives a member the choice of who reads it and no address field", () => {
    render(ui(member));
    expect(
      screen.getByText("Vem får läsa det du skriver?"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/Vi svarar till anna@exempel.se/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Din e-postadress")).not.toBeInTheDocument();
  });

  it("shows field errors and focuses the first, sending nothing", () => {
    render(ui(null));
    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    expect(
      screen.getByText("Välj om något inte fungerar eller om du önskar något."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Skriv några ord om vad det gäller."),
    ).toBeInTheDocument();
    expect(screen.getByText(/Skriv en e-postadress/)).toBeInTheDocument();
    expect(document.activeElement).toBe(
      screen.getByLabelText("Något fungerar inte"),
    );
    expect(send).not.toHaveBeenCalled();
  });

  async function fill() {
    fireEvent.click(screen.getByLabelText("Något fungerar inte"));
    fireEvent.change(screen.getByLabelText("Beskriv med egna ord"), {
      target: { value: "Knappen gör inget" },
    });
  }

  it("says so when the session ended while the form was open", async () => {
    send.mockResolvedValue({
      ok: false,
      status: 400,
      error: "Skriv en giltig e-postadress.",
      field: "email",
    });
    render(ui(member));
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    expect(
      await screen.findByText(
        "Du har blivit utloggad. Logga in igen och skicka, texten finns kvar.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Beskriv med egna ord")).toHaveValue(
      "Knappen gör inget",
    );
  });

  it("sends the fields the API expects and shows the receipt", async () => {
    send.mockResolvedValue({
      ok: true,
      issueUrl: null,
      visibility: "privat",
      images: 0,
      replyTo: "anna@exempel.se",
    });
    render(ui(member));
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    expect(
      await screen.findByText("Tack! Vi har fått din synpunkt."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Bara föreningen kan läsa den."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Vi svarar till anna@exempel.se."),
    ).toBeInTheDocument();
    const fd: FormData = send.mock.calls[0][0];
    expect(fd.get("typ")).toBe("fel");
    expect(fd.get("text")).toBe("Knappen gör inget");
    expect(fd.get("vem")).toBe("privat");
    expect(fd.get("sida")).toBe("/stamboken/min-besattning");
    expect(fd.get("inskick_id")).toMatch(/^[0-9a-f-]{36}$/);
    expect(fd.get("webbplats")).toBe("");
  });

  it("tries again with the same inskick_id when the first call is still working (409)", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    send
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        error: "Skickas redan.",
      })
      .mockResolvedValueOnce({
        ok: true,
        issueUrl: null,
        visibility: "privat",
        images: 0,
        replyTo: null,
      });
    render(ui(member));
    await fill();
    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    await vi.advanceTimersByTimeAsync(2100);
    await waitFor(() =>
      expect(
        screen.getByText("Tack! Vi har fått din synpunkt."),
      ).toBeInTheDocument(),
    );
    expect(send).toHaveBeenCalledTimes(2);
    expect(send.mock.calls[1][0].get("inskick_id")).toBe(
      send.mock.calls[0][0].get("inskick_id"),
    );
    vi.useRealTimers();
  });
});
