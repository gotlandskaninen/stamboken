import { describe, expect, it } from "vitest";
import {
  emptyState,
  fromBody,
  isDone,
  keyAfter,
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
  it("needs a choice, and a weight or Ej vägd for an adult that stays", () => {
    expect(isDone(adult, undefined, false)).toBe(false);
    expect(isDone(adult, e({ val: "kvar" }), false)).toBe(false);
    expect(isDone(adult, e({ val: "kvar", vikt: "2,8" }), false)).toBe(true);
    expect(
      isDone(adult, e({ val: "kvar", ej_vagd: "Har ingen våg" }), false),
    ).toBe(true);
    expect(isDone(young, e({ val: "kvar" }), false)).toBe(true);
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
        kopare: { name: "Ola", town: "Visby" },
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
  it("leaves out a choice that lacks its month, so that the server asks for it", () => {
    const s = state();
    s.rabbits[2] = e({
      val: "dod",
      dod: { ar: 2026, manad: null, dag: null, slaktad: false, anteckning: "" },
    });
    expect(toBody(s, "k", null).rabbits).not.toHaveProperty("2");
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

describe("keyAfter", () => {
  it("keeps the key after a timeout and renews it otherwise", () => {
    const k = "11111111-1111-4111-8111-111111111111";
    expect(keyAfter("timeout", k)).toBe(k);
    expect(keyAfter("ok", k)).not.toBe(k);
    expect(keyAfter("withdrawn", k)).not.toBe(k);
  });
});
