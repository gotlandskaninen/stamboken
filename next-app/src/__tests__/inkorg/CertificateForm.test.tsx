import "@testing-library/jest-dom/vitest";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

vi.mock("@/app/(app)/stamboken/(dashboard)/inkorg/actions", () => ({
  lookupRabbit: vi.fn(async () => null),
  saveCertificate: vi.fn(),
}));

import { CertificateForm } from "@/app/(app)/stamboken/(dashboard)/inkorg/[id]/CertificateForm";
import type {
  InboxDocument,
  Proposal,
} from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

afterEach(cleanup);

// A synthetic reading: the number read, the mother one character off, the
// father's branch against the registry, the birth date unreadable.
const PROPOSAL: Proposal = {
  fields: {
    paper_number: { value: "G9001-2511", source: "läst", read: "G9001 2511" },
    mother: { value: "G9001-2211", source: "härlett", read: "G9OO1 2211" },
    father: { value: null, source: "avviker", read: "G9002 2311" },
    birth_date: { value: null, source: "osäker", read: "10/5" },
    farfar: {
      value: null,
      source: "avviker",
      read: "G9003 2011",
      registry: "G9002-2011",
    },
  },
  checks: [
    { ok: true, text: "Intygsnumret är ledigt." },
    {
      ok: false,
      text: "Far: far- och morföräldrarna på intyget är inte registrets för G9002-2311.",
    },
  ],
};

const doc = (changes: Partial<InboxDocument> = {}): InboxDocument => ({
  id: 31,
  status: "ny",
  mime: "image/jpeg",
  warnings: [],
  duplicates: [],
  doc_type: "intyg",
  cert_format: null,
  rotation: 0,
  mask_rects: null,
  mask_suggestion: null,
  waiting_for: null,
  interpretation_status: "klar",
  proposal: PROPOSAL,
  individual: null,
  has_copy: false,
  ...changes,
});

const show = (d: InboxDocument) =>
  render(
    <CertificateForm
      itemId={12}
      doc={d}
      colors={["viltgrå"]}
      canSave
      onSaved={() => undefined}
      onSkip={() => undefined}
    />,
  );

const input = (label: RegExp) => screen.getByLabelText(label);
const sourceOf = (label: RegExp) =>
  input(label).closest("[data-source]")?.getAttribute("data-source") ?? null;

describe("CertificateForm with the image reading's proposal", () => {
  it("prefills läst and härlett, leaves avviker and osäker empty", () => {
    show(doc());
    expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-2511");
    expect(input(/^Mor/)).toHaveValue("G9001-2211");
    expect(input(/^Far(?!-)/)).toHaveValue("");
    expect(input(/^Födelsedatum/)).toHaveValue("");
  });

  it("colours each field by its source and shows what was read", () => {
    show(doc());
    expect(sourceOf(/^Individnummer på pappret/)).toBe("läst");
    expect(sourceOf(/^Mor/)).toBe("härlett");
    expect(sourceOf(/^Far(?!-)/)).toBe("avviker");
    expect(sourceOf(/^Födelsedatum/)).toBe("osäker");
    expect(sourceOf(/^Intygsnummer/)).toBeNull();
    expect(screen.getByText("Intyget: G9002 2311")).toBeInTheDocument();
    expect(
      screen.getByText("Intyget: G9003 2011 · Registret: G9002-2011"),
    ).toBeInTheDocument();
  });

  it("lists the checks under the form, with the note to compare with the photo", () => {
    show(doc());
    const checks = screen.getByRole("list", { name: "Kontroller" });
    const lines = within(checks).getAllByRole("listitem");
    expect(lines.map((li) => li.getAttribute("data-ok"))).toEqual([
      "true",
      "false",
    ]);
    expect(checks).toHaveTextContent("Intygsnumret är ledigt.");
    expect(screen.getByText(/Jämför varje fält med fotot/)).toBeInTheDocument();
  });

  it("opens on the paper certificate when the rabbit is in Stamboken", () => {
    const found: Proposal = {
      fields: { individual: { value: "G9001-2411", source: "läst" } },
      checks: [
        { ok: true, text: "G9001-2411 finns redan med digitalt intyg." },
      ],
    };
    show(doc({ proposal: found }));
    expect(
      screen.getByRole("button", {
        name: "Pappersintyg på en kanin som finns",
      }),
    ).toHaveAttribute("aria-pressed", "true");
    expect(input(/^Individnummer i Stamboken/)).toHaveValue("G9001-2411");
  });

  it("while the photo is read, or when it failed, the form is empty", () => {
    show(doc({ interpretation_status: "vantar", proposal: null }));
    expect(screen.getByText(/Fotot tolkas/)).toBeInTheDocument();
    expect(input(/^Individnummer på pappret/)).toHaveValue("");
    cleanup();
    show(doc({ interpretation_status: "misslyckad" }));
    expect(screen.getByText(/Fotot gick inte att tolka/)).toBeInTheDocument();
    expect(input(/^Mor/)).toHaveValue("");
    expect(screen.queryByRole("list", { name: "Kontroller" })).toBeNull();
  });
});
