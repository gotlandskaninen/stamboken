import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import {
  render,
  screen,
  cleanup,
  fireEvent,
  waitFor,
} from "@testing-library/react";

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
  updateConsent: vi.fn(),
}));

import { updateConsent } from "@/app/(app)/stamboken/(dashboard)/profil/actions";
import { PubliceringClient } from "@/app/(app)/stamboken/(dashboard)/profil/PubliceringClient";
import {
  CONSENT_TEXT,
  CONSENT_TEXT_VERSION,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

type Consent = {
  name: boolean;
  phone: boolean;
  email: boolean;
  address: boolean;
};
const V = CONSENT_TEXT_VERSION;
const NEJ = { name: false, phone: false, email: false, address: false };
const JA_EMAIL = { name: true, phone: false, email: true, address: false };

const renderIt = (initial: Consent, answered = true, readOnly = false) =>
  render(
    <PubliceringClient
      readOnly={readOnly}
      initial={initial}
      answered={answered}
    />,
  );
const radio = (name: string) =>
  screen.getByRole("radio", { name }) as HTMLInputElement;
const box = (name: string) =>
  screen.getByRole("checkbox", { name }) as HTMLInputElement;
const save = () =>
  fireEvent.click(screen.getByRole("button", { name: "Spara" }));
const acknowledge = (consent: Consent) =>
  vi.mocked(updateConsent).mockResolvedValue({
    ok: true,
    consent,
    answered: true,
  });

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("PubliceringClient", () => {
  it("asks the paper form's Koharen question", () => {
    renderIt(JA_EMAIL);
    expect(screen.getByText("Publicering i Koharen")).toBeDefined();
    expect(screen.getByText(CONSENT_TEXT)).toBeDefined();
    expect(screen.getByRole("radiogroup", { name: "Publicering i Koharen" }));
    expect(screen.getByText(/Inget av detta visas på webben/)).toBeDefined();
    expect(screen.queryByText(/Medlemsmatrikeln/)).toBeNull();
    // Only the paper form has a choice for no answer.
    expect(screen.queryByRole("radio", { name: /Inget svar/ })).toBeNull();
  });

  it("prefills Ja with what may appear", () => {
    renderIt(JA_EMAIL);
    expect(radio("Ja").checked).toBe(true);
    expect(box("telefonnummer").checked).toBe(false);
    expect(box("e-postadress").checked).toBe(true);
    expect(box("postnummer och ort").checked).toBe(false);
  });

  it("prefills Nej when the name may not appear, whatever else is stored", () => {
    renderIt({ ...NEJ, phone: true });
    expect(radio("Nej").checked).toBe(true);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("chooses nothing for a member who never answered, and saves nothing", () => {
    renderIt(NEJ, false);
    expect(radio("Ja").checked).toBe(false);
    expect(radio("Nej").checked).toBe(false);
    expect(
      (screen.getByRole("button", { name: "Spara" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(updateConsent).not.toHaveBeenCalled();
  });

  it("sends all four keys with the first answer, a Nej too", async () => {
    acknowledge(NEJ);
    renderIt(NEJ, false);
    fireEvent.click(radio("Nej"));
    save();
    await waitFor(() =>
      expect(updateConsent).toHaveBeenCalledWith({ ...NEJ, text_version: V }),
    );
  });

  it("sends only the keys that changed", async () => {
    acknowledge({ ...JA_EMAIL, phone: true });
    renderIt(JA_EMAIL);
    fireEvent.click(box("telefonnummer"));
    save();
    await waitFor(() =>
      expect(showSnackbar).toHaveBeenCalledWith(
        "Publiceringsval sparade",
        "success",
      ),
    );
    expect(updateConsent).toHaveBeenCalledWith({
      phone: true,
      text_version: V,
    });
  });

  it("sends a Nej whole", async () => {
    acknowledge(NEJ);
    renderIt(JA_EMAIL);
    fireEvent.click(radio("Nej"));
    save();
    await waitFor(() =>
      expect(updateConsent).toHaveBeenCalledWith({ ...NEJ, text_version: V }),
    );
  });

  it("sends a new Ja whole: a key another tab allowed is not kept", async () => {
    // The tab opened on Nej; another tab saved Ja with e-post meanwhile.
    // This Ja allows only the name, so e-post must go up as false.
    acknowledge({ ...NEJ, name: true });
    renderIt(NEJ);
    fireEvent.click(radio("Ja"));
    expect(box("telefonnummer").checked).toBe(false);
    expect(box("e-postadress").checked).toBe(false);
    expect(box("postnummer och ort").checked).toBe(false);
    save();
    await waitFor(() =>
      expect(updateConsent).toHaveBeenCalledWith({
        ...NEJ,
        name: true,
        text_version: V,
      }),
    );
  });

  it("does not PATCH an untouched answer", async () => {
    renderIt(JA_EMAIL);
    save();
    await waitFor(() =>
      expect(showSnackbar).toHaveBeenCalledWith(
        "Publiceringsval sparade",
        "success",
      ),
    );
    expect(updateConsent).not.toHaveBeenCalled();
  });

  it("diffs the next save against what the server acknowledged, not the refreshed prop", async () => {
    // Another tab withdraws e-post while this one is open. This tab allows
    // the phone number; the backend merges and answers email=false. The next
    // save must not send the email=true this tab mounted with.
    const merged = { name: true, phone: true, email: false, address: false };
    acknowledge(merged);
    const view = renderIt(JA_EMAIL);
    fireEvent.click(box("telefonnummer"));
    save();
    await waitFor(() =>
      expect(updateConsent).toHaveBeenCalledWith({
        phone: true,
        text_version: V,
      }),
    );
    await waitFor(() => expect(box("e-postadress").checked).toBe(false));
    view.rerender(<PubliceringClient initial={merged} answered />);
    vi.mocked(updateConsent).mockClear();
    save();
    await waitFor(() => expect(showSnackbar).toHaveBeenCalledTimes(2));
    expect(updateConsent).not.toHaveBeenCalled();
  });

  it("shows the error and keeps the answer when the save fails", async () => {
    vi.mocked(updateConsent).mockResolvedValue({ ok: false, error: "Fel" });
    renderIt(JA_EMAIL);
    fireEvent.click(radio("Nej"));
    save();
    await waitFor(() =>
      expect(showSnackbar).toHaveBeenCalledWith("Fel", "error"),
    );
    expect(radio("Nej").checked).toBe(true);
  });

  it("locks the question and Spara when readOnly", () => {
    renderIt(JA_EMAIL, true, true);
    expect(
      screen.getByText(
        "Endast huvudmedlemmen kan ändra medlemskapets uppgifter.",
      ),
    ).toBeDefined();
    for (const input of [
      ...screen.getAllByRole("radio"),
      ...screen.getAllByRole("checkbox"),
    ])
      expect((input as HTMLInputElement).disabled).toBe(true);
    expect(
      (screen.getByRole("button", { name: "Spara" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });
});
