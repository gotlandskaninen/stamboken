import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import "@/i18n";
import { ModeProvider } from "@/lib/mode-context";
import type { Mode } from "@/lib/mode";
import { DigitalCertificate } from "@/components/individual/DigitalCertificate";
import type { Individual } from "@/redux/api/apiSlice";

const TOKEN = "3f2a9c1e-0000-4000-8000-000000000001";
const V2 = { verification_token: TOKEN, issued_at: "2026-11-23T23:30:00" };

function renderFor(fields: Partial<Individual>, mode: Mode = "prod") {
  const individual = {
    number: "G1274-2301",
    digital_certificate: "4711",
    can_view_certificate: true,
    current_certificate: V2,
    ...fields,
  } as Individual;
  return render(
    <ModeProvider mode={mode}>
      <DigitalCertificate individual={individual} />
    </ModeProvider>,
  );
}

const pdfLink = () =>
  screen.queryByRole("link", {
    name: /Visa intyg/,
  }) as HTMLAnchorElement | null;
const verifyLink = () =>
  screen.queryByRole("link", {
    name: "Kontrollera intyget",
  }) as HTMLAnchorElement | null;
const ONLY_FOR =
  "Bara kaninens ägare, uppfödaren och genbanksansvarig kan hämta intyget.";

afterEach(cleanup);

describe("DigitalCertificate", () => {
  it("opens the PDF in a new tab for those who may, with the verification page beside it", () => {
    renderFor({});
    expect(pdfLink()?.getAttribute("href")).toBe(
      "/api/v2/certificates/G1274-2301",
    );
    expect(pdfLink()?.getAttribute("target")).toBe("_blank");
    expect(pdfLink()?.textContent).toContain("(öppnas i en ny flik)");
    expect(verifyLink()?.getAttribute("href")).toBe(
      `/stamboken/verifiera/${TOKEN}`,
    );
    expect(screen.queryByText(ONLY_FOR)).toBeNull();
  });

  it("dates the certificate as the server does, with no time zone shift", () => {
    renderFor({});
    expect(screen.getByText("Utfärdat 2026-11-23")).toBeDefined();
  });

  it("tells everyone else who may, and links the verification page only", () => {
    renderFor({ can_view_certificate: false });
    expect(pdfLink()).toBeNull();
    expect(screen.getByText(ONLY_FOR)).toBeDefined();
    expect(verifyLink()?.getAttribute("href")).toBe(
      `/stamboken/verifiera/${TOKEN}`,
    );
  });

  it("has no verification page for a v1 certificate, but the owner still opens it", () => {
    renderFor({ current_certificate: null });
    expect(pdfLink()).not.toBeNull();
    expect(verifyLink()).toBeNull();
    expect(screen.queryByText(/Utfärdat/)).toBeNull();
  });

  it("leaves a v1 certificate as the note alone for everyone else", () => {
    renderFor({ current_certificate: null, can_view_certificate: false });
    expect(screen.getByText(ONLY_FOR)).toBeDefined();
    expect(screen.queryAllByRole("link")).toHaveLength(0);
  });

  it("opens no PDF in the test environment", () => {
    renderFor({}, "demo");
    expect(pdfLink()).toBeNull();
    expect(screen.getByText("Intyget visas inte i testmiljön.")).toBeDefined();
    expect(verifyLink()).not.toBeNull();
  });

  it("still opens a current PDF whose number was lost (ADR-0019)", () => {
    renderFor({ digital_certificate: null });
    expect(pdfLink()).not.toBeNull();
    expect(verifyLink()).not.toBeNull();
  });

  it("renders nothing without a digital certificate", () => {
    const { container } = renderFor({
      digital_certificate: null,
      current_certificate: null,
    });
    expect(container.innerHTML).toBe("");
  });
});
