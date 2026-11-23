import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import {
  MailFacts,
  SenderUnconfirmed,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/MailFacts";
import type { InboxDetail } from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

afterEach(cleanup);

const item = (detail: Record<string, unknown>) =>
  ({
    events: [{ id: 1, at: "", kind: "inkommen", user: null, detail }],
  }) as unknown as InboxDetail;

describe("MailFacts", () => {
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
    expect(screen.getByText("brev.docx, stor.jpg")).toBeInTheDocument();
  });

  it("shows nothing for an upload", () => {
    const { container } = render(
      <dl>
        <MailFacts item={item({ documents: 2 })} />
      </dl>,
    );
    expect(container.querySelector("dt")).toBeNull();
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
