import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const updateContact = vi.fn();
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
  konto: null,
};

describe("MemberDetails", () => {
  it("changes the e-mail in place through the profile's code, and says the session ends", async () => {
    updateContact.mockResolvedValue({ ok: true, codeSent: true });
    verifyEmailCode.mockResolvedValue({ ok: true });
    render(
      <MemberDetails
        details={main}
        fields={detailsFields(main)}
        onChange={vi.fn()}
        returnTo="/stamboken/arsrapport/G9001/2026"
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Byt e-postadress" }));
    expect(screen.getByText(/När adressen är bytt loggas du ut/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Ny e-postadress"), {
      target: { value: " ny@example.invalid " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Skicka kod" }));
    expect(await screen.findByLabelText("Kod")).toBeTruthy();
    expect(updateContact).toHaveBeenCalledWith({
      email: "ny@example.invalid",
    });
    fireEvent.change(screen.getByLabelText("Kod"), {
      target: { value: "1234 5678" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Byt adress" }));
    const login = await screen.findByRole("link", { name: "Logga in" });
    expect(verifyEmailCode).toHaveBeenCalledWith("1234 5678");
    expect(login.getAttribute("href")).toBe(
      "/auth/sign-in?return_to=%2Fstamboken%2Farsrapport%2FG9001%2F2026",
    );
  });

  it("shows nothing for paper, whose fields are PaperChanges", () => {
    const { container } = render(
      <MemberDetails
        details={{ mode: "paper" }}
        fields={detailsFields()}
        onChange={vi.fn()}
        returnTo="/"
      />,
    );
    expect(container.textContent).toBe("");
  });
});
