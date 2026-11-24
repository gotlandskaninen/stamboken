import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  MailFacts,
  MailThread,
  SenderUnconfirmed,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/MailFacts";
import type { InboxDetail } from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

afterEach(cleanup);

const item = (detail: Record<string, unknown>) =>
  ({
    mentioned_individuals: [],
    events: [{ id: 1, at: "", kind: "inkommen", user: null, detail }],
  }) as unknown as InboxDetail;

describe("MailFacts", () => {
  it("links to the rabbits the reader may see", () => {
    render(
      <dl>
        <MailFacts item={{ ...item({}), mentioned_individuals: ["G1-2112"] }} />
      </dl>,
    );
    expect(screen.getByText("Nämnda kaniner")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "G1-2112" })).toHaveAttribute(
      "href",
      "/stamboken/individ/G1-2112",
    );
  });

  it("shows the case a reply may be about and the files not stored", () => {
    render(
      <dl>
        <MailFacts
          item={item({
            documents: 1,
            maybe_item: 12,
            not_saved: ["brev.docx", "stor.jpg"],
          })}
        />
      </dl>,
    );
    expect(screen.getByRole("link", { name: "Ärende 12" })).toHaveAttribute(
      "href",
      "/stamboken/inkorg/12",
    );
    expect(screen.getByText("Sparades inte")).toBeInTheDocument();
    expect(screen.getByText("brev.docx")).toBeInTheDocument();
    expect(screen.getByText("stor.jpg")).toBeInTheDocument();
  });

  it.each(["inkommen", "svar"])(
    "shows why a file in %s was skipped",
    (kind) => {
      const mail = item({
        not_saved: ["logo.png"],
        not_saved_reasons: [
          { name: "logo.png", reason: "Bilden är för liten." },
        ],
      });
      mail.events[0].kind = kind;
      render(
        <dl>
          <MailFacts item={mail} />
        </dl>,
      );
      expect(
        screen.getByText("logo.png – Bilden är för liten."),
      ).toBeInTheDocument();
    },
  );

  it("shows nothing for an upload", () => {
    const { container } = render(
      <dl>
        <MailFacts item={item({ documents: 2 })} />
      </dl>,
    );
    expect(container.querySelector("dt")).toBeNull();
  });
});

describe("MailThread", () => {
  it("keeps each subject with its own message", () => {
    const mail = item({ subject: "Första ämnet" });
    mail.kind = "meddelande";
    mail.message = "Första raden.\nAndra raden.";
    mail.events.push({
      id: 2,
      kind: "svar",
      at: "2026-11-24T10:00:00Z",
      user: null,
      detail: { subject: "Komplettering", text: "Svar på frågan." },
    });
    render(<MailThread item={mail} />);
    const [first, reply] = screen.getAllByRole("article");
    expect(first).toHaveTextContent("ÄmneFörsta ämnet");
    expect(first.querySelector("p")?.textContent).toBe(mail.message);
    expect(reply).toHaveTextContent("ÄmneKomplettering");
    expect(reply).toHaveTextContent("Svar på frågan.");
  });

  it("shows a subject without a body and hides a purged message", () => {
    const { rerender } = render(
      <MailThread item={item({ subject: "Intyg" })} />,
    );
    expect(screen.getByText("Intyg")).toBeVisible();
    rerender(<MailThread item={item({ documents: 1 })} />);
    expect(screen.queryByRole("region")).toBeNull();
  });
});

describe("SenderUnconfirmed", () => {
  const sender = (sender_authenticated: boolean | null) =>
    ({ sender_authenticated }) as InboxDetail;
  it("says so, and that no mail goes to the address, when it is false", () => {
    render(<SenderUnconfirmed item={sender(false)} />);
    expect(
      screen.getByText("Avsändaren är inte bekräftad"),
    ).toBeInTheDocument();
    expect(screen.getByText(/Inget mejl skickas/)).toBeInTheDocument();
  });
  it.each([true, null])("shows nothing for %s", (value) => {
    const { container } = render(<SenderUnconfirmed item={sender(value)} />);
    expect(container).toBeEmptyDOMElement();
  });
});
