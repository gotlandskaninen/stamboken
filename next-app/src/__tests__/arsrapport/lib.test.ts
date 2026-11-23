import { describe, expect, it } from "vitest";
import {
  emptyState,
  fromBody,
  deathDateOk,
  editClears,
  incompleteText,
  isDone,
  keyAfter,
  autosaveAnswerKept,
  parseWeight,
  toBody,
  toDraft,
  type Entry,
  type FormState,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";
import { rabbit } from "./fixtures";

const e = (over: Partial<Entry>): Entry => ({
  val: null,
  vikt: "",
  ej_vagd: null,
  hull: null,
  dod: null,
  sald: null,
  ...over,
});

describe("parseWeight", () => {
  it("takes comma and point as kilos", () => {
    expect(parseWeight("2,8").kg).toBe(2.8);
    expect(parseWeight("2.8").kg).toBe(2.8);
  });
  it("reads above 100 as grams", () => {
    expect(parseWeight("2800")).toEqual({
      kg: null,
      gramsHint: 2.8,
      unusual: false,
    });
  });
  it("reads 20 to 100 as a missing decimal comma", () => {
    expect(parseWeight("72")).toEqual({
      kg: null,
      gramsHint: 7.2,
      unusual: false,
    });
    expect(parseWeight("20").kg).toBe(20);
  });
  it("flags weights outside 1,0 to 6,5 and ignores empty text", () => {
    expect(parseWeight("7,2").unusual).toBe(true);
    expect(parseWeight("0,5").unusual).toBe(true);
    expect(parseWeight("").kg).toBeNull();
    expect(parseWeight("abc").kg).toBeNull();
  });
});

describe("isDone", () => {
  const adult = rabbit(1);
  const young = rabbit(2, { adult: false });
  it("counts an adult a rejected sale left as Finns kvar, and sends it back unchanged (S6)", () => {
    // as the server stores the entry: Finns kvar with Ej vägd
    const stored = {
      val: "kvar",
      vikt: null,
      ej_vagd: "Försäljningen avvisades",
      hull: null,
      dod: null,
      sald: null,
    };
    const state = fromBody({ rabbits: { "1": stored } } as never);
    expect(isDone(adult, state.rabbits[1], false)).toBe(true);
    expect(toBody(state, "k", 2).rabbits["1"]).toEqual({
      val: "kvar",
      vikt: null,
      ej_vagd: "Försäljningen avvisades",
      hull: null,
    });
  });
  it("needs a choice, and a weight or Ej vägd for an adult that stays", () => {
    expect(isDone(adult, undefined, false)).toBe(false);
    expect(isDone(adult, e({ val: "kvar" }), false)).toBe(false);
    expect(isDone(adult, e({ val: "kvar", vikt: "2,8" }), false)).toBe(true);
    expect(
      isDone(adult, e({ val: "kvar", ej_vagd: "Har ingen våg" }), false),
    ).toBe(true);
    expect(isDone(young, e({ val: "kvar" }), false)).toBe(true);
  });
  it("does not count a weight the server refuses until it is fixed", () => {
    for (const vikt of ["72", "2800"])
      expect(isDone(adult, e({ val: "kvar", vikt }), false)).toBe(false);
    expect(isDone(adult, e({ val: "kvar", vikt: "7,2" }), false)).toBe(true);
  });
  it("needs a month for a death and a sale", () => {
    const dod = {
      ar: 2026,
      manad: null,
      dag: null,
      slaktad: false,
      anteckning: "",
    };
    expect(isDone(adult, e({ val: "dod", dod }), false)).toBe(false);
    expect(
      isDone(adult, e({ val: "dod", dod: { ...dod, manad: 3 } }), false),
    ).toBe(true);
  });
  it("needs nothing when the genebank ends, and counts a kept ej_angiven and a rabbit counted by its move", () => {
    expect(isDone(adult, e({ val: "kvar" }), true)).toBe(true);
    expect(isDone(adult, e({ val: "ej_angiven" }), false)).toBe(true);
    expect(isDone(rabbit(3, { state: "via_flytt" }), undefined, false)).toBe(
      true,
    );
  });
  it("does not count a sale outside the genebank whose buyer Skicka would miss", () => {
    const sale = { till: "utanfor", ar: 2026, manad: 6, dag: null };
    const sold = (more: object) =>
      e({ val: "sald", sald: { ...sale, kopare: null, ...more } });
    // only in the draft, which never holds the buyer: restored after a reload
    expect(isDone(adult, sold({}), false)).toBe(false);
    expect(isDone(adult, sold({}), false, null)).toBe(false);
    // the report's own sale, unchanged; changed, it is a new sale
    expect(isDone(adult, sold({}), false, sale)).toBe(true);
    expect(isDone(adult, sold({ manad: 7 }), false, sale)).toBe(false);
    // typed in this session, or a kept buyer only a role that sells may use
    const buyer = { name: "Ola Köpare", town: "Visby" } as never;
    expect(isDone(adult, sold({ kopare: buyer }), false)).toBe(true);
    const kept = { ...adult, kept_buyer_date: "2026-06-01" };
    expect(
      isDone(kept, sold({ dag: 1, kopare_id: 7 }), false, null, true),
    ).toBe(true);
    expect(
      isDone(kept, sold({ dag: 2, kopare_id: 7 }), false, null, true),
    ).toBe(false);
    expect(isDone({ ...adult, buyer_removed: true }, sold({}), false)).toBe(
      true,
    );
    expect(
      isDone(kept, sold({ dag: 1, kopare_id: 7 }), false, null, false),
    ).toBe(false);
    // a sale to a herd in the genebank has no such buyer
    expect(isDone(adult, sold({ till: "G9002" }), false)).toBe(true);
  });
});

describe("editClears", () => {
  const dod = { ar: 2026, manad: 3, dag: 4, slaktad: false, anteckning: "" };
  const before = e({ val: "dod", dod });
  it("keeps a death-date refusal when only the note or Slaktad changes", () => {
    for (const patch of [
      { dod: { ...dod, anteckning: "x" } },
      { dod: { ...dod, slaktad: true } },
    ])
      expect(editClears("dodsdatum_ogiltigt", before, patch, true)).toBe(false);
    expect(
      editClears(
        "dodsdatum_ogiltigt",
        before,
        { dod: { ...dod, dag: 5 } },
        true,
      ),
    ).toBe(true);
  });
  it("keeps a death-date refusal while the new date is still before the birth", () => {
    const born = "2026-06-10";
    const moved = { dod: { ...dod, dag: 5 } };
    expect(editClears("dodsdatum_ogiltigt", before, moved, true, born)).toBe(
      false,
    );
    const fixed = { dod: { ...dod, manad: 7, dag: 1 } };
    expect(editClears("dodsdatum_ogiltigt", before, fixed, true, born)).toBe(
      true,
    );
  });
  it("judges a death date like the server", () => {
    const d = (ar: number, manad: number, dag: number | null) => ({
      ar,
      manad,
      dag,
    });
    expect(deathDateOk(d(2026, 12, null), null, "2026-11-15")).toBe(false);
    expect(deathDateOk(d(2026, 11, null), null, "2026-11-15")).toBe(true);
    expect(deathDateOk(d(2026, 11, 20), null, "2026-11-15")).toBe(false);
    expect(deathDateOk(d(2026, 5, null), "2026-05-31", "2026-11-15")).toBe(
      true,
    );
    expect(deathDateOk(d(2026, 5, 2), "2026-05-31", "2026-11-15")).toBe(false);
  });
  it("clears a weight refusal on a weight edit, keeps register refusals", () => {
    const kvar = e({ val: "kvar", vikt: "x" });
    expect(editClears("vikt_ogiltig", kvar, { vikt: "2,8" }, true)).toBe(true);
    expect(editClears("vikt_ogiltig", kvar, { hull: "normal" }, false)).toBe(
      false,
    );
    expect(editClears("senare_handelse", kvar, { vikt: "2,8" }, true)).toBe(
      false,
    );
  });
  it("clears inte_klar when the row becomes klar", () => {
    expect(
      editClears(
        "inte_klar",
        before,
        { dod: { ...dod, anteckning: "x" } },
        true,
      ),
    ).toBe(true);
  });
});

describe("incompleteText", () => {
  const dod = {
    ar: 2026,
    manad: null,
    dag: null,
    slaktad: false,
    anteckning: "",
  };
  it("names what a half-filled death or sale lacks", () => {
    expect(incompleteText(e({ val: "dod", dod }))).toBe("Välj månad.");
    expect(
      incompleteText(e({ val: "sald", sald: { till: "", manad: 3 } as never })),
    ).toBe("Ange köparen.");
    expect(
      incompleteText(
        e({ val: "sald", sald: { till: "Anna, Visby", manad: null } as never }),
      ),
    ).toBe("Välj månad.");
    expect(incompleteText(e({ val: "kvar" }))).toBeNull();
    expect(
      incompleteText(e({ val: "dod", dod: { ...dod, manad: 3 } })),
    ).toBeNull();
  });
});

const state = (): FormState => ({
  ...emptyState(),
  rabbits: {
    1: e({ val: "kvar", vikt: "2,8", hull: "normal" }),
    2: e({
      val: "dod",
      dod: { ar: 2026, manad: 5, dag: null, slaktad: true, anteckning: "Sjuk" },
    }),
    3: e({
      val: "sald",
      sald: {
        till: "utanfor",
        ar: 2026,
        manad: 6,
        dag: 14,
        kopare: {
          name: "Ola",
          town: "Visby",
          contact_consent: true,
          membership_optin: false,
          email: "ola@example.invalid",
        },
      },
    }),
  },
  health: "ja",
  diseases: {
    ...emptyState().diseases,
    rvhd: { antal: "2", alder: "unga", namn: "" },
  },
  defects: [{ individual_id: 1, beskrivning: "Sned tand" }],
  message: "Hej",
});

describe("draft and body", () => {
  it("round-trips a draft without the buyers", () => {
    const s = state();
    const withoutBuyers = {
      ...s,
      rabbits: {
        ...s.rabbits,
        3: { ...s.rabbits[3], sald: { ...s.rabbits[3].sald!, kopare: null } },
      },
    };
    expect(fromBody(toDraft(s))).toEqual(withoutBuyers);
    expect(JSON.stringify(toDraft(s))).not.toMatch(
      /matrikel|kopare|Ola|submission_key|revision/,
    );
  });
  it("sends the buyer in the body, and a saved sale without it", () => {
    expect(toBody(state(), "k", 3).rabbits["3"].sald?.kopare).toMatchObject({
      name: "Ola",
      town: "Visby",
    });
    const saved = fromBody(toDraft(state()));
    expect(toBody(saved, "k", 3).rabbits["3"].sald).not.toHaveProperty(
      "kopare",
    );
  });
  it("sends the buyer's yes as given, never a hard-coded no", () => {
    expect(toBody(state(), "k", 3).rabbits["3"].sald?.kopare).toEqual({
      name: "Ola",
      town: "Visby",
      contact_consent: true,
      membership_optin: false,
      email: "ola@example.invalid",
    });
  });
  it("carries a kept buyer's id through the draft and into the body, for a sale outside only (K1)", () => {
    const s = state();
    s.rabbits[3] = {
      ...s.rabbits[3],
      sald: { ...s.rabbits[3].sald!, kopare: null, kopare_id: 7 },
    };
    const saved = fromBody(toDraft(s));
    expect(saved.rabbits[3].sald?.kopare_id).toBe(7);
    expect(toBody(saved, "k", null).rabbits["3"].sald).toMatchObject({
      kopare_id: 7,
    });
    expect(toBody(saved, "k", null).rabbits["3"].sald).not.toHaveProperty(
      "kopare",
    );
    saved.rabbits[3].sald!.till = "G9002";
    expect(toBody(saved, "k", null).rabbits["3"].sald).not.toHaveProperty(
      "kopare_id",
    );
  });
  it("leaves out a choice that lacks its month, so that the server asks for it", () => {
    const s = state();
    s.rabbits[2] = e({
      val: "dod",
      dod: { ar: 2026, manad: null, dag: null, slaktad: false, anteckning: "" },
    });
    expect(toBody(s, "k", null).rabbits).not.toHaveProperty("2");
  });
  it("sends only the rabbits on the current list", () => {
    // FB1: a rabbit whose sale was approved has left the list, but a local copy may still hold it
    const s = state();
    s.defects = [...s.defects, { individual_id: 3, beskrivning: "Kort öra" }];
    const b = toBody(s, "k", null, [1, 2]);
    expect(Object.keys(b.rabbits).sort()).toEqual(["1", "2"]);
    expect(b.defects.map((d) => d.individual_id)).toEqual([1]);
  });
  it("sends the weight as a number and Ej vägd instead of a weight", () => {
    const b = toBody(state(), "k", null).rabbits;
    expect(b["1"].vikt).toBe(2.8);
    const s = state();
    s.rabbits[1] = e({ val: "kvar", vikt: "2", ej_vagd: "Har ingen våg" });
    expect(toBody(s, "k", null).rabbits["1"]).toMatchObject({
      vikt: null,
      ej_vagd: "Har ingen våg",
    });
  });
});

describe("an unfinished draft", () => {
  it("round-trips a death without a month and a disease without a count", () => {
    const s = emptyState();
    s.rabbits[1] = e({
      val: "dod",
      dod: {
        ar: 2026,
        manad: null,
        dag: null,
        slaktad: false,
        anteckning: "x",
      },
    });
    s.health = "ja";
    s.diseases.rvhd = { antal: "", alder: "unga", namn: "" };
    expect(fromBody(toDraft(s))).toEqual(s);
  });
});

describe("the stored form is an allow-list", () => {
  it("drops unknown keys, a matrikel and a buyer on the way in and out", () => {
    const evil = {
      matrikel: { telefon: "0700" },
      extra: 1,
      rabbits: {
        1: {
          val: "sald",
          vikt: "2",
          sald: {
            till: "utanfor",
            ar: 2026,
            manad: 6,
            dag: null,
            kopare: { name: "Ola" },
          },
          matrikel: {},
        },
      },
      diseases: { rvhd: { antal: "1", alder: "", namn: "", kopare: "x" } },
      defects: [
        { individual_id: 1, beskrivning: "x", epost: "a@example.invalid" },
      ],
    };
    const state = fromBody({ form: evil as never });
    expect(JSON.stringify(state)).not.toMatch(
      /matrikel|0700|Ola|extra|epost|example/,
    );
    expect(state.rabbits[1].sald?.kopare).toBeNull();
    const draft = JSON.stringify(toDraft(state));
    expect(draft).not.toMatch(/matrikel|0700|Ola|extra|epost|example|kopare/);
  });
});

describe("a malformed stored draft", () => {
  it("never throws and falls back to a usable form", () => {
    expect(() => fromBody({ form: { defects: {} } } as never)).not.toThrow();
    expect(fromBody({ form: { defects: {} } } as never).defects).toEqual([]);
    const bad = {
      form: "text",
      defects: {},
      rabbits: "x",
      diseases: 3,
    } as never;
    expect(fromBody(bad)).toEqual(emptyState());
    expect(fromBody({ form: [] } as never)).toEqual(emptyState());
    expect(fromBody(null as never)).toEqual(emptyState());
  });
});

describe("a body-shaped draft with wrong types", () => {
  it("normalises every rabbit field instead of copying it", () => {
    const rabbit = (over: object) =>
      fromBody({ rabbits: { "123": { val: "kvar", ...over } } } as never)
        .rabbits[123];
    expect(() => rabbit({ ej_vagd: {} })).not.toThrow();
    expect(rabbit({ ej_vagd: {} }).ej_vagd).toBeNull();
    expect(rabbit({ vikt: {} }).vikt).toBe("");
    expect(rabbit({ vikt: 2.8 }).vikt).toBe("2,8");
    expect(rabbit({ hull: {} }).hull).toBeNull();
    expect(rabbit({ val: {} }).val).toBeNull();
    expect(rabbit({ val: "bogus" }).val).toBeNull();
    const dod = fromBody({
      rabbits: {
        "1": {
          val: "dod",
          dod: { ar: {}, manad: "5", dag: [], slaktad: "x", anteckning: 3 },
        },
      },
    } as never).rabbits[1].dod;
    expect(dod).toEqual({
      ar: 0,
      manad: 5,
      dag: null,
      slaktad: true,
      anteckning: "",
    });
    const sald = fromBody({
      rabbits: {
        "1": {
          val: "sald",
          sald: { till: {}, ar: "2026", manad: {}, dag: "x" },
        },
      },
    } as never).rabbits[1].sald;
    expect(sald).toEqual({
      till: "",
      ar: 2026,
      manad: null,
      dag: null,
      kopare: null,
    });
    const s = fromBody({
      rabbits: "x",
      ending_genbank: {},
      membership_after_end: {},
      health: {},
      diseases: {
        rvhd: { antal: {}, alder: {} },
        annat: { antal: 2, namn: [] },
      },
      defects: [
        { individual_id: {}, beskrivning: "x" },
        7,
        { individual_id: 4, beskrivning: {} },
      ],
      message: {},
      reason: [],
    } as never);
    expect(s).toMatchObject({
      ending: true,
      membership: null,
      health: null,
      message: "",
      reason: "",
    });
    expect(s.diseases.rvhd.antal).toBe("");
    expect(s.diseases.annat).toEqual({ antal: "2", alder: "", namn: "" });
    expect(s.defects).toEqual([{ individual_id: 4, beskrivning: "" }]);
  });
});

describe("keyAfter", () => {
  it("keeps the key after a timeout and renews it otherwise", () => {
    const k = "11111111-1111-4111-8111-111111111111";
    expect(keyAfter("timeout", k)).toBe(k);
    expect(keyAfter("ok", k)).not.toBe(k);
    expect(keyAfter("withdrawn", k)).not.toBe(k);
  });
});

describe("autosaveAnswerKept", () => {
  it("keeps an answer only when no submission started since the save left", () => {
    expect(autosaveAnswerKept(0, 0)).toBe(true);
    expect(autosaveAnswerKept(1, 1)).toBe(true);
    expect(autosaveAnswerKept(0, 1)).toBe(false);
  });
});
