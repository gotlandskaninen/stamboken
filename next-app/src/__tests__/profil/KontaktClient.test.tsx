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
}));

import { updateContact } from "@/app/(app)/stamboken/(dashboard)/profil/actions";
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
    vi.mocked(updateContact).mockResolvedValue({ ok: true });
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
    vi.mocked(updateContact).mockResolvedValue({ ok: true });
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
