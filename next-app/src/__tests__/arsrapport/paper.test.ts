import { describe, expect, it } from "vitest";
import {
  emptyPaperFields,
  formDocumentIds,
  intygPending,
  matrikelBody,
  paperKey,
  type PaperState,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";
import { reportYears } from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";
import type { InboxDetail } from "@/app/(app)/stamboken/(dashboard)/inkorg/lib";

const press = (s: PaperState, ...keys: string[]) =>
  keys.reduce(paperKey, s as PaperState) as PaperState;
const at = (field: PaperState["field"], val: PaperState["val"] = null) => ({
  field,
  val,
});

describe("paperKey", () => {
  it("1, 2 and 3 choose on the radio group and move on", () => {
    expect(paperKey(at("val"), "1")).toEqual(at("vikt", "kvar"));
    expect(paperKey(at("val"), "2")).toEqual(at("month", "dod"));
    expect(paperKey(at("val"), "3")).toEqual(at("sold", "sald"));
  });

  it("never chooses from a text field: a digit in Vikt stays a digit", () => {
    for (const field of ["number", "vikt", "ej_vagd", "hull", "month"] as const)
      expect(paperKey(at(field, "kvar"), "1")).toEqual(at(field, "kvar"));
  });

  it("Enter in the number field picks, and the chain runs to the next row", () => {
    expect(paperKey(at("number"), "Enter")).toEqual(at("val"));
    expect(press(at("vikt", "kvar"), "Enter", "Enter", "Enter")).toEqual(
      at("number", "kvar"),
    );
    expect(press(at("val"), "1", "Tab", "Tab", "Enter").field).toBe("number");
  });

  it("after Död, Enter walks month, day, Slaktad, Anteckning, then the next row", () => {
    const keys = ["2", "Enter", "Enter", "Enter", "Enter"];
    const fields = [];
    let st = at("val");
    for (const k of keys) {
      st = paperKey(st, k);
      fields.push(st.field);
    }
    expect(fields).toEqual(["month", "day", "slaktad", "note", "number"]);
    expect(paperKey(at("sold", "sald"), "Enter").field).toBe("number");
  });

  it("Tab goes on from Vikt to Ej vägd, but leaves the last field alone", () => {
    expect(paperKey(at("vikt", "kvar"), "Tab")).toEqual(at("ej_vagd", "kvar"));
    expect(paperKey(at("hull", "kvar"), "Tab")).toEqual(at("hull", "kvar"));
  });

  it("ignores other keys", () => {
    expect(paperKey(at("val"), "x")).toEqual(at("val"));
    expect(paperKey(at("val"), "4")).toEqual(at("val"));
  });
});

describe("matrikelBody", () => {
  it("leaves empty fields out, and sends nothing when none is filled", () => {
    expect(matrikelBody(emptyPaperFields())).toBeNull();
    const f = emptyPaperFields();
    f.telefon = " 070-1 ";
    f.adress.city = "Visby";
    f.konto.konto = "1234567";
    expect(matrikelBody(f)).toEqual({
      telefon: "070-1",
      adress: { city: "Visby" },
      konto: { konto: "1234567" },
    });
  });

  it("gives Nej as {ja: false, utom: []} and Ja with its exceptions", () => {
    const nej = { ...emptyPaperFields(), consent: "nej" as const };
    expect(matrikelBody(nej)).toEqual({ publicering: { ja: false, utom: [] } });
    const ja = {
      ...emptyPaperFields(),
      consent: "ja" as const,
      utom: ["phone" as const],
    };
    expect(matrikelBody(ja)).toEqual({
      publicering: { ja: true, utom: ["phone"] },
    });
  });

  it("drops the exceptions of a No, and an empty consent is no answer", () => {
    const f = {
      ...emptyPaperFields(),
      consent: "nej" as const,
      utom: ["email" as const],
    };
    expect(matrikelBody(f)?.publicering).toEqual({ ja: false, utom: [] });
    expect(
      matrikelBody({ ...emptyPaperFields(), epost: "a@example.invalid" }),
    ).toEqual({ epost: "a@example.invalid" });
  });
});

const doc = (
  id: number,
  doc_type: string,
  status: string,
  waiting?: string[],
) => ({ id, doc_type, status, waiting_for: waiting ?? null }) as never;
const item = (documents: unknown[]) =>
  ({ documents }) as unknown as InboxDetail;

describe("formDocumentIds", () => {
  it("gives the form pages that are not done, and leaves the intyg", () => {
    expect(
      formDocumentIds(
        item([
          doc(1, "arsblankett", "ny"),
          doc(2, "intyg", "ny"),
          doc(3, "arsblankett", "ny"),
        ]),
      ),
    ).toEqual([1, 3]);
  });

  it("skips pages that are already done or dismissed", () => {
    expect(
      formDocumentIds(
        item([doc(1, "arsblankett", "avfardad"), doc(2, "arsblankett", "ny")]),
      ),
    ).toEqual([2]);
  });
});

describe("intygPending", () => {
  it("holds the form back for an open or waiting intyg", () => {
    expect(intygPending(item([doc(1, "intyg", "ny")]))).toBe(true);
    expect(intygPending(item([doc(1, "intyg", "sparad")]))).toBe(true);
    expect(
      intygPending(item([doc(1, "bevis", "vantar_foralder", ["G1-2"])])),
    ).toBe(true);
  });
  it("lets the form through when the others are done", () => {
    expect(
      intygPending(
        item([
          doc(1, "intyg", "klar"),
          doc(2, "annat", "avfardad"),
          doc(3, "arsblankett", "ny"),
        ]),
      ),
    ).toBe(false);
  });
});

describe("reportYears", () => {
  const round = (
    year: number,
    genebanks: number[],
    start_date: string | null = `${year}-12-31`,
    end_date: string | null = `${year + 1}-03-30`,
  ) => ({
    year,
    start_date,
    end_date,
    genebanks: genebanks.map((genebank_id) => ({ genebank_id })),
  });
  const rounds = [round(2025, [1]), round(2026, [2]), round(2027, [])];
  it("is the round the item's genebank has open today", () => {
    expect(reportYears(rounds, 1, "2026-02-01")).toEqual([2025]);
    expect(reportYears(rounds, 2, "2027-02-01")).toEqual([2026]);
  });
  it("is the latest activated round once the last one closed", () => {
    expect(reportYears(rounds, 1, "2026-11-01")).toEqual([2025]);
  });
  it("offers the closed year too while the next has not opened (#264)", () => {
    const both = [round(2026, [1]), round(2027, [1])];
    expect(reportYears(both, 1, "2027-05-10")).toEqual([2026, 2027]);
    expect(reportYears(both, 1, "2027-12-31")).toEqual([2027]); // the new round is open
  });
  it("offers only the activated round before the first one opens", () => {
    expect(reportYears([round(2026, [1])], 1, "2026-12-20")).toEqual([2026]);
  });
  it("is empty without a genebank, a round or an activation", () => {
    expect(reportYears(rounds, 3, "2026-02-01")).toEqual([]);
    expect(reportYears(rounds, null, "2026-02-01")).toEqual([]);
    expect(reportYears(null, 1, "2026-02-01")).toEqual([]);
  });
});
