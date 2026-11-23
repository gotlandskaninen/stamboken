import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";
import { ThemeProvider } from "@mui/material/styles";
import { stambokenTheme } from "@/theme/stamboken";

const { showSnackbar, addNotification } = vi.hoisted(() => ({
  showSnackbar: vi.fn(),
  addNotification: vi.fn(),
}));
vi.mock("@/components/SnackbarProvider", () => ({
  useSnackbar: () => ({ showSnackbar }),
}));
vi.mock("@/contexts/NotificationContext", () => ({
  useNotifications: () => ({ addNotification }),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/profil/actions", () => ({
  updateContact: vi.fn(),
  verifyEmailCode: vi.fn(),
}));

import {
  updateContact,
  verifyEmailCode,
} from "@/app/(app)/stamboken/(dashboard)/profil/actions";
import { KontaktClient } from "@/app/(app)/stamboken/(dashboard)/profil/KontaktClient";

const initial = {
  phone: "070-1234567",
  email: "anna@example.com",
  address: "Storgatan 1",
  postal_code: "623 55",
  city: "Visby",
};
const renderIt = (readOnly = false) =>
  render(
    <ThemeProvider theme={stambokenTheme}>
      <KontaktClient readOnly={readOnly} initial={initial} />
    </ThemeProvider>,
  );

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("KontaktClient", () => {
  it("renders the five fields from initial values", () => {
    renderIt();
    expect(
      (screen.getByLabelText("Gatuadress") as HTMLInputElement).value,
    ).toBe("Storgatan 1");
    expect(
      (screen.getByLabelText("Postnummer") as HTMLInputElement).value,
    ).toBe("623 55");
    expect((screen.getByLabelText("Postort") as HTMLInputElement).value).toBe(
      "Visby",
    );
    expect(
      screen.getByText(
        /Vad som trycks i Koharen styr du under Publicering i Koharen/,
      ),
    ).toBeDefined();
  });

  it("formats a compact postnummer on blur and refuses to save an invalid one", () => {
    renderIt();
    const input = screen.getByLabelText("Postnummer") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "62145" } });
    fireEvent.blur(input);
    expect(input.value).toBe("621 45");
    fireEvent.change(input, { target: { value: "12" } });
    fireEvent.blur(input);
    expect(
      (screen.getByRole("button", { name: "Spara" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText("Postnummer ska vara fem siffror")).toBeDefined();
  });

  it("saves all five fields and confirms with a snackbar", async () => {
    vi.mocked(updateContact).mockResolvedValue({ ok: true, codeSent: false });
    renderIt();
    fireEvent.change(screen.getByLabelText("Postort"), {
      target: { value: "Lärbro" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(showSnackbar).toHaveBeenCalledWith(
        "Kontaktuppgifter sparade",
        "success",
      ),
    );
    expect(updateContact).toHaveBeenCalledWith({ ...initial, city: "Lärbro" });
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("omits an empty e-mail from the patch so a member without one can save", async () => {
    vi.mocked(updateContact).mockResolvedValue({ ok: true, codeSent: false });
    render(
      <ThemeProvider theme={stambokenTheme}>
        <KontaktClient initial={{ ...initial, email: "" }} />
      </ThemeProvider>,
    );
    const postal = screen.getByLabelText("Postnummer") as HTMLInputElement;
    fireEvent.change(postal, { target: { value: "62145" } });
    fireEvent.blur(postal);
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(updateContact).toHaveBeenCalled());
    const body = vi.mocked(updateContact).mock.calls[0][0];
    // The API rejects a present-but-empty email before it looks at the
    // address fields, so the key must be absent, not "".
    expect("email" in body).toBe(false);
    expect(body).toEqual(
      expect.not.objectContaining({ email: expect.anything() }),
    );
    expect(body).toEqual({
      phone: initial.phone,
      address: initial.address,
      postal_code: "621 45",
      city: initial.city,
    });
  });

  it("asks for the code a new address got, and says to sign in again once it is changed", async () => {
    vi.mocked(updateContact).mockResolvedValue({ ok: true, codeSent: true });
    vi.mocked(verifyEmailCode).mockResolvedValue({ ok: true });
    renderIt();
    expect(screen.queryByLabelText("Kod")).toBeNull();
    fireEvent.change(screen.getByLabelText("E-post"), {
      target: { value: "ny@example.org" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    const input = (await screen.findByLabelText("Kod")) as HTMLInputElement;
    // type=number would drop leading zeros; the phone gets digits and may offer the code
    expect(input.type).toBe("text");
    expect(input.getAttribute("inputmode")).toBe("numeric");
    expect(input.getAttribute("autocomplete")).toBe("one-time-code");
    fireEvent.change(input, { target: { value: "0482 7195" } });
    fireEvent.click(screen.getByRole("button", { name: "Byt adress" }));
    await waitFor(() =>
      expect(screen.getByRole("status").textContent).toContain(
        "Nu är adressen bytt",
      ),
    );
    expect(verifyEmailCode).toHaveBeenCalledWith("0482 7195");
    expect(
      screen.getByRole("link", { name: "Logga in" }).getAttribute("href"),
    ).toBe("/auth/sign-in?return_to=/stamboken/profil");
  });

  it("keeps the code step and shows the error on a wrong code", async () => {
    vi.mocked(updateContact).mockResolvedValue({ ok: true, codeSent: true });
    vi.mocked(verifyEmailCode).mockResolvedValue({
      ok: false,
      error: "Koden stämmer inte eller har gått ut.",
    });
    renderIt();
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    fireEvent.change(await screen.findByLabelText("Kod"), {
      target: { value: "12345678" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Byt adress" }));
    await waitFor(() =>
      expect(showSnackbar).toHaveBeenCalledWith(
        "Koden stämmer inte eller har gått ut.",
        "error",
      ),
    );
    expect(screen.getByLabelText("Kod")).toBeDefined();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("says when the test environment refuses a new address", async () => {
    vi.mocked(updateContact).mockResolvedValue({
      ok: true,
      codeSent: false,
      emailRefused: "E-postadressen kan inte bytas i testmiljön.",
    });
    renderIt();
    fireEvent.change(screen.getByLabelText("E-post"), {
      target: { value: "ny@example.org" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() =>
      expect(showSnackbar).toHaveBeenCalledWith(
        "E-postadressen kan inte bytas i testmiljön.",
        "warning",
      ),
    );
    expect(screen.queryByLabelText("Kod")).toBeNull();
  });

  it("locks every field and explains why when readOnly", () => {
    renderIt(true);
    expect(
      screen.getByText(
        "Endast huvudmedlemmen kan ändra medlemskapets uppgifter.",
      ),
    ).toBeDefined();
    for (const label of [
      "Telefon",
      "E-post",
      "Gatuadress",
      "Postnummer",
      "Postort",
    ]) {
      expect((screen.getByLabelText(label) as HTMLInputElement).disabled).toBe(
        true,
      );
    }
    expect(
      (screen.getByRole("button", { name: "Spara" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});
