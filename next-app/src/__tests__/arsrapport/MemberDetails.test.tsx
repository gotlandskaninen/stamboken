import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const updateContact = vi.fn();
const saveReportContact = vi.fn();
const saveReportConsent = vi.fn();
const saveAccount = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/arsrapport/actions", () => ({
  saveAccount: (...a: unknown[]) => saveAccount(...a),
  saveReportContact: (...a: unknown[]) => saveReportContact(...a),
  saveReportConsent: (...a: unknown[]) => saveReportConsent(...a),
}));
const verifyEmailCode = vi.fn();
const cancelEmailCode = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/profil/actions", () => ({
  updateContact: (...a: unknown[]) => updateContact(...a),
  verifyEmailCode: (...a: unknown[]) => verifyEmailCode(...a),
  cancelEmailCode: (...a: unknown[]) => cancelEmailCode(...a),
}));

import { MemberDetails } from "@/app/(app)/stamboken/(dashboard)/arsrapport/MemberDetails";
import {
  detailsFields,
  type MemberDetailsView,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

const main: MemberDetailsView = {
  mode: "main",
  contact: {
    address: "Gamla vägen 1",
    postal_code: "621 41",
    city: "Slite",
    phone: "",
    email: "g9001@example.invalid",
  },
  publicering: null,
  publicering_version: null,
  konto: null,
};

const props = {
  details: main,
  fields: detailsFields(main),
  onChange: vi.fn(),
  herd: "G9001",
  year: 2026,
  env: "demo" as const,
};

describe("MemberDetails", () => {
  it("saves contact once on blur and shows the field result", async () => {
    saveReportContact
      .mockResolvedValueOnce({ ok: true })
      .mockResolvedValueOnce({
        ok: false,
        problem: { detail: "Försök igen." },
      });
    render(<MemberDetails {...props} />);
    const phone = screen.getByLabelText("Telefon");
    fireEvent.change(phone, { target: { value: "010-000 00 01" } });
    expect(saveReportContact).not.toHaveBeenCalled();
    fireEvent.blur(phone);
    expect(await screen.findByText("Kontaktuppgifter sparade")).toBeTruthy();
    fireEvent.blur(phone);
    expect(saveReportContact).toHaveBeenCalledTimes(1);
    expect(saveReportContact).toHaveBeenCalledWith(
      "G9001",
      2026,
      "phone",
      "010-000 00 01",
      "demo",
    );
    fireEvent.change(phone, { target: { value: "" } });
    fireEvent.blur(phone);
    expect((await screen.findByRole("alert")).textContent).toBe("Försök igen.");
  });

  it("saves publication on change against the last acknowledged revision", async () => {
    saveReportConsent.mockResolvedValue({
      ok: true,
      data: { publicering_version: 12 },
    });
    render(<MemberDetails {...props} />);
    fireEvent.click(screen.getByRole("radio", { name: "Ja" }));
    expect(await screen.findByText("Publiceringsval sparade")).toBeTruthy();
    const answer = {
      ja: true,
      utom: ["phone", "email", "address"],
      text_version: "2026-11-20",
    };
    expect(saveReportConsent).toHaveBeenCalledWith(
      "G9001",
      2026,
      { ...answer, version: null },
      "demo",
    );
    fireEvent.click(screen.getByRole("checkbox", { name: "telefonnummer" }));
    expect(await screen.findByText("Publiceringsval sparade")).toBeTruthy();
    expect(saveReportConsent).toHaveBeenLastCalledWith(
      "G9001",
      2026,
      { ...answer, utom: ["email", "address"], version: 12 },
      "demo",
    );
  });

  it("saves a complete account only with Spara kontot", async () => {
    saveAccount.mockResolvedValue({ ok: true, data: { konto: "••67" } });
    render(<MemberDetails {...props} />);
    fireEvent.click(
      screen.getByRole("button", { name: "Nytt konto för stödet" }),
    );
    fireEvent.click(screen.getByRole("radio", { name: "Bankgiro" }));
    const save = screen.getByRole("button", {
      name: "Spara kontot",
    }) as HTMLButtonElement;
    const number = screen.getByLabelText("Kontonummer");
    fireEvent.change(number, { target: { value: "123" } });
    expect(save.disabled).toBe(true);
    fireEvent.change(number, { target: { value: "123-4567" } });
    fireEvent.blur(number);
    expect(saveAccount).not.toHaveBeenCalled();
    expect(save.disabled).toBe(false);
    fireEvent.click(save);
    expect(await screen.findByText("Konto för stödet: ••67")).toBeTruthy();
    expect(saveAccount).toHaveBeenCalledTimes(1);
    expect(saveAccount).toHaveBeenCalledWith(
      "G9001",
      2026,
      { typ: "bankgiro", konto: "123-4567" },
      "demo",
    );
  });

  it("sends a code only with Skicka kod, once, and verifies before sign-in", async () => {
    updateContact.mockResolvedValue({ ok: true, codeSent: true });
    verifyEmailCode.mockResolvedValue({ ok: true });
    render(<MemberDetails {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Byt e-postadress" }));
    expect(screen.getByText(/När adressen är bytt loggas du ut/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Ny e-postadress"), {
      target: { value: " ny@example.invalid " },
    });
    fireEvent.blur(screen.getByLabelText("Ny e-postadress"));
    expect(updateContact).not.toHaveBeenCalled(); // a half-typed address gets no mail
    fireEvent.click(screen.getByRole("button", { name: "Skicka kod" }));
    fireEvent.click(screen.getByRole("button", { name: "Skicka kod" }));
    expect(updateContact).toHaveBeenCalledTimes(1);
    expect(await screen.findByLabelText("Kod")).toBeTruthy();
    expect(updateContact).toHaveBeenCalledWith(
      {
        email: "ny@example.invalid",
      },
      "demo",
    );
    fireEvent.change(screen.getByLabelText("Kod"), {
      target: { value: "1234 5678" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Byt adress" }));
    const login = await screen.findByRole("link", { name: "Logga in" });
    expect(verifyEmailCode).toHaveBeenCalledWith("1234 5678", "demo");
    expect(login.getAttribute("href")).toBe(
      "/auth/sign-in?return_to=%2Fstamboken%2Farsrapport%2FG9001%2F2026",
    );
  });

  it("shows nothing for paper, whose fields are PaperChanges", () => {
    const { container } = render(
      <MemberDetails {...props} details={{ mode: "paper" }} />,
    );
    expect(container.textContent).toBe("");
  });
});
