import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";

const requestReportEmailCode = vi.fn();
const verifyReportEmailCode = vi.fn();
const cancelReportEmailCode = vi.fn();
const saveReportContact = vi.fn();
const saveReportConsent = vi.fn();
const saveAccount = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/arsrapport/actions", () => ({
  requestReportEmailCode: (...a: unknown[]) => requestReportEmailCode(...a),
  verifyReportEmailCode: (...a: unknown[]) => verifyReportEmailCode(...a),
  cancelReportEmailCode: (...a: unknown[]) => cancelReportEmailCode(...a),
  saveAccount: (...a: unknown[]) => saveAccount(...a),
  saveReportContact: (...a: unknown[]) => saveReportContact(...a),
  saveReportConsent: (...a: unknown[]) => saveReportConsent(...a),
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

  it("saves the latest phone after a pending blur", async () => {
    const first = Promise.withResolvers<void>();
    const second = Promise.withResolvers<void>();
    saveReportContact
      .mockReturnValueOnce(first.promise.then(() => ({ ok: true })))
      .mockReturnValueOnce(second.promise.then(() => ({ ok: true })));
    render(<MemberDetails {...props} />);
    const phone = screen.getByLabelText("Telefon") as HTMLInputElement;
    for (const value of [
      "010-000 00 01",
      "010-000 00 02",
      main.contact.phone,
    ]) {
      expect(phone.disabled).toBe(false);
      fireEvent.change(phone, { target: { value } });
      fireEvent.blur(phone);
    }
    expect(saveReportContact).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve());
    expect(saveReportContact).toHaveBeenCalledTimes(2);
    expect(saveReportContact).toHaveBeenLastCalledWith(
      "G9001",
      2026,
      "phone",
      "",
      "demo",
    );
    expect(screen.queryByText("Kontaktuppgifter sparade")).toBeNull();
    await act(async () => second.resolve());
    expect(screen.getByText("Kontaktuppgifter sparade")).toBeTruthy();
  });

  it("saves the latest Koharen answer with the acknowledged revision", async () => {
    const first = Promise.withResolvers<void>();
    saveReportConsent
      .mockReturnValueOnce(
        first.promise.then(() => ({
          ok: true,
          data: { publicering_version: 12 },
        })),
      )
      .mockResolvedValueOnce({ ok: true, data: { publicering_version: 13 } });
    render(<MemberDetails {...props} />);
    fireEvent.click(screen.getByRole("radio", { name: "Ja" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "telefonnummer" }));
    fireEvent.click(screen.getByRole("radio", { name: "Nej" }));
    expect(saveReportConsent).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve());
    expect(saveReportConsent).toHaveBeenCalledTimes(2);
    expect(saveReportConsent).toHaveBeenLastCalledWith(
      "G9001",
      2026,
      {
        ja: false,
        utom: [],
        text_version: "2026-11-20",
        version: 12,
      },
      "demo",
    );
    expect(screen.getByText("Publiceringsval sparade")).toBeTruthy();
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

  it("requests and verifies a code for the displayed report", async () => {
    requestReportEmailCode.mockResolvedValue({
      ok: true,
      data: { email_code_sent: true },
    });
    verifyReportEmailCode.mockResolvedValue({ ok: true });
    render(<MemberDetails {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Byt e-postadress" }));
    expect(screen.getByText(/När adressen är bytt loggas du ut/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Ny e-postadress"), {
      target: { value: " ny@example.invalid " },
    });
    fireEvent.blur(screen.getByLabelText("Ny e-postadress"));
    expect(requestReportEmailCode).not.toHaveBeenCalled(); // a half-typed address gets no mail
    fireEvent.click(screen.getByRole("button", { name: "Skicka kod" }));
    fireEvent.click(screen.getByRole("button", { name: "Skicka kod" }));
    expect(requestReportEmailCode).toHaveBeenCalledTimes(1);
    expect(await screen.findByLabelText("Kod")).toBeTruthy();
    expect(requestReportEmailCode).toHaveBeenCalledWith(
      "G9001",
      2026,
      "ny@example.invalid",
      "demo",
    );
    fireEvent.change(screen.getByLabelText("Kod"), {
      target: { value: "1234 5678" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Byt adress" }));
    const login = await screen.findByRole("link", { name: "Logga in" });
    expect(verifyReportEmailCode).toHaveBeenCalledWith(
      "G9001",
      2026,
      "1234 5678",
      "demo",
    );
    expect(login.getAttribute("href")).toBe(
      "/auth/sign-in?return_to=%2Fstamboken%2Farsrapport%2FG9001%2F2026",
    );
  });

  it("cancels a code for the displayed report", async () => {
    requestReportEmailCode.mockResolvedValue({
      ok: true,
      data: { email_code_sent: true },
    });
    cancelReportEmailCode.mockResolvedValue({ ok: true });
    render(<MemberDetails {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "Byt e-postadress" }));
    fireEvent.change(screen.getByLabelText("Ny e-postadress"), {
      target: { value: "ny@example.org" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Skicka kod" }));
    await screen.findByLabelText("Kod");
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    await screen.findByRole("button", { name: "Byt e-postadress" });
    expect(cancelReportEmailCode).toHaveBeenCalledWith("G9001", 2026, "demo");
  });

  it("shows nothing for paper, whose fields are PaperChanges", () => {
    const { container } = render(
      <MemberDetails {...props} details={{ mode: "paper" }} />,
    );
    expect(container.textContent).toBe("");
  });
});
