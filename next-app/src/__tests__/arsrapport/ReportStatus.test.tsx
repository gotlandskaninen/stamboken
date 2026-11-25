import React from "react";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  ReportStatus,
  type StatusKind,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/ReportStatus";

afterEach(cleanup);

// Every text of the state table in the design brief, section 6.
const cases: [StatusKind, string][] = [
  [
    { kind: "saved", at: "14.32", changing: false },
    "Inte inskickad. Det du fyllt i är sparat (senast 14.32).",
  ],
  [
    { kind: "saved", at: "10.12", changing: true },
    "Ändringar som inte är inskickade (sparade 10.12). Den inskickade rapporten gäller tills du skickar.",
  ],
  [{ kind: "saving" }, "Sparar …"],
  [
    { kind: "offline", device: "telefonen" },
    "Inte sparat än, ingen anslutning. Det du fyllt i finns kvar i telefonen.",
  ],
  [
    { kind: "offline", device: "webbläsaren" },
    "Inte sparat än, ingen anslutning. Det du fyllt i finns kvar i webbläsaren.",
  ],
  [
    { kind: "conflict" },
    "Rapporten har ändrats på en annan enhet. Vi har läst in den senaste.",
  ],
  [{ kind: "sending" }, "Skickar…"],
  [
    { kind: "timeout" },
    "Vi vet inte om rapporten kom fram. Tryck Försök igen. Den skickas inte två gånger.",
  ],
  [
    { kind: "withdrawn", date: "5 januari 2027" },
    "Dragen tillbaka 5 januari 2027. Inte inskickad. Det du fyllt i är sparat.",
  ],
  [
    { kind: "closed" },
    "Rundan är stängd. Kontakta genbanksansvarig om något behöver ändras.",
  ],
  [
    { kind: "late", deadline: "31 januari 2027" },
    "Sista dag för stödet var 31 januari 2027. Rapportera ändå, så räknas dina kaniner.",
  ],
  [
    { kind: "editor", herd: "G9001" },
    "Du ser G9001:s rapport som genbanksansvarig.",
  ],
];

describe("ReportStatus", () => {
  it.each(cases)("%j", (status, text) => {
    render(<ReportStatus status={status} />);
    expect(screen.getByText(text)).toBeTruthy();
  });
  it("links the logged-out text to the sign-in", () => {
    render(
      <ReportStatus status={{ kind: "loggedout", href: "/auth/sign-in" }} />,
    );
    expect(
      screen.getByRole("link", { name: "Logga in igen" }).getAttribute("href"),
    ).toBe("/auth/sign-in");
    expect(screen.getByRole("status").textContent).toBe(
      "Du har loggats ut. Logga in igen. Det du fyllt i finns kvar i webbläsaren.",
    );
  });
});
