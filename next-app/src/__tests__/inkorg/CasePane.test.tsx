import "@testing-library/jest-dom/vitest";
import "@/i18n";
import i18n from "i18next";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ModeProvider } from "@/lib/mode-context";
import { CasePane } from "@/app/(app)/stamboken/(dashboard)/inkorg/CasePane";
import type {
  InboxDetail,
  InboxDocument,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

const { changeState } = vi.hoisted(() => ({ changeState: vi.fn() }));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/actions", () => ({
  changeState,
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/ItemControls", () => ({
  ItemControls: () => null,
}));

const now = Date.parse("2026-11-24T11:00:00Z");
const received = "2026-11-24T10:00:00Z";
const user = { id: 1, is_manager: [1], is_admin: false };
const letter = {
  id: 12,
  kind: "mail",
  state: "tagen",
  genebank_id: 1,
  herd: "G9001",
  received_at: received,
  state_changed_at: received,
  closed_at: null,
  sender: null,
  assigned_to: { id: 1, name: "Konto 1" },
  assigned_at: received,
  duplicate_of: null,
  stalled: false,
  missing_proof: false,
  ref_type: null,
  ref_id: null,
  has_message: true,
  maybe_blurry: false,
  documents_done: 0,
  documents: [],
  sender_address: "inkorg@example.org",
  sender_authenticated: true,
  message: "Här är beviset.\nNästa rad.",
  mentioned_individuals: ["G9001-2611"],
  events: [
    {
      id: 1,
      at: received,
      kind: "inkommen",
      user: null,
      detail: {
        subject: "Beviset för kaninen",
        not_saved_reasons: [
          { name: "bevis.png", reason: "Filen är för liten." },
        ],
      },
    },
    {
      id: 2,
      at: received,
      kind: "svar",
      user: null,
      detail: {
        subject: "En rättelse",
        text: "Det ska stå 2026.",
      },
    },
  ],
} satisfies InboxDetail;

function view(
  changes: Partial<InboxDetail> = {},
  nextHref: string | null = "/stamboken/inkorg?arende=17",
) {
  return render(
    <ModeProvider mode="prod">
      <CasePane
        item={{ ...letter, ...changes }}
        user={user}
        myGenebanks={[1]}
        backHref="/stamboken/inkorg?herd=G9001"
        nextHref={nextHref}
        now={now}
      />
    </ModeProvider>,
  );
}

afterEach(cleanup);
beforeEach(() => changeState.mockReset());

describe("CasePane", () => {
  it("keeps the subject, full mail thread, skipped files and accessible rabbits together", () => {
    view();
    expect(
      screen.getByRole("heading", { name: "#12 Beviset för kaninen" }),
    ).toBeVisible();
    expect(screen.getByText("Här är beviset. Nästa rad.").textContent).toBe(
      letter.message,
    );
    expect(screen.getByText("En rättelse")).toBeVisible();
    expect(screen.getByText("Det ska stå 2026.")).toBeVisible();
    expect(screen.getByText("bevis.png – Filen är för liten.")).toBeVisible();
    expect(screen.getByRole("link", { name: "G9001-2611" })).toHaveAttribute(
      "href",
      "/stamboken/individ/G9001-2611",
    );
    expect(screen.getByText("inkorg@example.org")).toBeVisible();
    expect(screen.getByRole("link", { name: "Nästa ärende" })).toHaveAttribute(
      "href",
      "/stamboken/inkorg?arende=17",
    );
    expect(
      screen.getByRole("link", { name: "Tillbaka till listan" }),
    ).toHaveAttribute("href", "/stamboken/inkorg?herd=G9001");
  });

  it("can still open the complete registration view for a closed case", () => {
    view({ state: "klar" }, null);
    expect(
      screen.getByRole("link", { name: "Visa registrering och historik" }),
    ).toHaveAttribute("href", "/stamboken/inkorg/12");
    expect(screen.getByRole("button", { name: "Nästa ärende" })).toBeDisabled();
  });

  it.each([
    ["en", "Next case", "Email"],
    ["de", "Nächster Vorgang", "E-Mail"],
  ])(
    "localizes pane labels in %s and preserves the sender's subject and text",
    async (language, next, mail) => {
      await i18n.changeLanguage(language);
      try {
        view({ subject: " " });
        expect(screen.getByRole("link", { name: next })).toBeVisible();
        expect(screen.getByRole("heading", { name: mail })).toBeVisible();
        expect(
          screen.getByRole("heading", { name: "#12 Beviset för kaninen" }),
        ).toBeVisible();
        expect(screen.getByText("Här är beviset. Nästa rad.")).toBeVisible();
      } finally {
        cleanup();
        await i18n.changeLanguage("sv");
      }
    },
  );

  it("shows an omitted reply attachment without sending a request to the original sender", () => {
    view({
      events: [
        { ...letter.events[0], detail: { subject: "Ämne" } },
        {
          ...letter.events[1],
          detail: { sender_member: 42, not_saved: ["rattelse.png"] },
        },
      ],
    });
    expect(screen.getByText("rattelse.png")).toBeVisible();
    expect(
      screen.getByRole("heading", { name: /^Sparades inte i svaret/ }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Be avsändaren bifoga bilden" }),
    ).toBeNull();
  });

  it("prepares an editable message, then uses the existing incomplete-case sender notification", async () => {
    changeState.mockResolvedValueOnce({
      ok: false,
      problem: { detail: "Ärendet har ändrats." },
    });
    view();
    fireEvent.click(
      screen.getByRole("button", { name: "Be avsändaren bifoga bilden" }),
    );
    expect(changeState).not.toHaveBeenCalled();
    fireEvent.change(
      screen.getByRole("textbox", { name: "Meddelande till avsändaren" }),
      { target: { value: "Bifoga bevis.png." } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Skicka" }));
    await waitFor(() =>
      expect(changeState).toHaveBeenCalledWith(12, "ofullstandig", {
        note: "Bifoga bevis.png.",
      }),
    );
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Ärendet har ändrats.",
    );
  });

  it.each([
    { sender_authenticated: false },
    { sender_address: null },
    { state: "ny" as const, assigned_to: null },
    { genebank_id: 2 },
    { assigned_to: { id: 2, name: "Konto 2" } },
  ])(
    "only offers a request to an available recipient and by the current handler",
    (changes) => {
      view(changes);
      expect(
        screen.queryByRole("button", { name: "Be avsändaren bifoga bilden" }),
      ).toBeNull();
      expect(screen.getByText("bevis.png – Filen är för liten.")).toBeVisible();
    },
  );

  it("opens one photo at a time, resets zoom on selection and explains a deleted original", () => {
    const base = {
      id: 1,
      status: "ny",
      mime: "image/jpeg",
      warnings: [],
      duplicates: [],
      doc_type: "intyg",
      cert_format: null,
      rotation: 90,
      mask_rects: null,
      mask_suggestion: null,
      waiting_for: null,
      interpretation_status: "av",
      proposal: null,
      individual: null,
      has_copy: false,
      has_original: true,
    } satisfies InboxDocument;
    view({
      documents: [
        base,
        { ...base, id: 2 },
        { ...base, id: 3, has_original: false },
      ],
    });
    expect(screen.getByText("Foto 1 av 3")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Zooma in" }));
    expect(screen.getByRole("button", { name: "Zooma ut" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    fireEvent.click(screen.getByRole("button", { name: "Foto 2" }));
    expect(screen.getByText("Foto 2 av 3")).toBeVisible();
    expect(screen.getByRole("button", { name: "Zooma in" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    fireEvent.click(screen.getByRole("button", { name: "Foto 3" }));
    expect(screen.getByText("Originalet är raderat.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Zooma in" })).toBeNull();
  });
});
