import { describe, expect, it } from "vitest";
import {
  buildTestbreedRequest,
  createSequence,
  describeGenerations,
  formatDecimal,
  formatOffspringF,
  formatPercent,
  EMPTY_LAYOUT,
  deriveMaleSlots,
  editLayout,
  effectiveSelection,
  emptySlot,
  layoutFor,
  MAX_MALES,
  paramsFromSearch,
  parseProvparningParams,
  replaceMale,
  pickedFromIndividual,
  serializeProvparningParams,
  settleLayout,
  slotNow,
  sortResults,
  tooManyMales,
  verdictFor,
  withDetails,
  type AnimalInput,
  type Slot,
} from "@/lib/provparning";

const T = { good_max: 4, check_max: 6 };
const picked = (number: string, sex = "male") =>
  pickedFromIndividual({ number, name: null, sex, herd: "G1", alive: true });
const animal = (patch: Partial<AnimalInput> = {}): AnimalInput => ({
  key: "k",
  picked: null,
  unregistered: false,
  mother: null,
  father: null,
  ...patch,
});

describe("verdictFor", () => {
  it("applies the 4 / 6 % boundaries (inclusive upper bounds)", () => {
    expect(verdictFor(0, T)).toBe("good");
    expect(verdictFor(4, T)).toBe("good");
    expect(verdictFor(4.01, T)).toBe("check");
    expect(verdictFor(6, T)).toBe("check");
    expect(verdictFor(6.01, T)).toBe("high");
  });
  it("uses the thresholds it is given", () => {
    expect(verdictFor(10, { good_max: 12, check_max: 15 })).toBe("good");
  });
});

describe("Swedish number formatting", () => {
  it("uses a decimal comma", () => {
    expect(formatDecimal(3.12, 1)).toBe("3,1");
    expect(formatDecimal(3, 2)).toBe("3,00");
  });
  it("appends a non-breaking space and percent sign", () => {
    expect(formatPercent(3.12)).toBe("3,1 %");
    expect(formatPercent(25, 0)).toBe("25 %");
  });
  it("shows one decimal normally", () => {
    expect(formatOffspringF(3.12, T)).toBe("3,1 %");
    expect(formatOffspringF(0, T)).toBe("0,0 %");
    expect(formatOffspringF(4.6, T)).toBe("4,6 %");
  });
  it("shows two decimals when one decimal would cross a verdict boundary", () => {
    // 4,04 is "Utred närmare"; "4,0" next to that badge would read as "Bra".
    expect(formatOffspringF(4.04, T)).toBe("4,04 %");
    expect(formatOffspringF(6.04, T)).toBe("6,04 %");
  });
});

describe("URL params", () => {
  it("parses repeated hane, trims and dedupes", () => {
    expect(
      parseProvparningParams({
        genebank: "1",
        hona: " G1274-2112 ",
        hane: ["G1274-2201", "G1301-2104", "G1274-2201", ""],
      }),
    ).toEqual({
      genebank: 1,
      hona: "G1274-2112",
      hane: ["G1274-2201", "G1301-2104"],
    });
  });
  it("accepts a single hane and ignores a bad genebank", () => {
    expect(parseProvparningParams({ genebank: "x", hane: "G1-1" })).toEqual({
      genebank: null,
      hona: null,
      hane: ["G1-1"],
    });
    expect(parseProvparningParams({})).toEqual({
      genebank: null,
      hona: null,
      hane: [],
    });
  });
  it("caps the number of males at 10", () => {
    const hane = Array.from({ length: 15 }, (_, i) => `G1-${i}`);
    expect(parseProvparningParams({ hane }).hane).toHaveLength(10);
  });
  it("serialises with repeated hane and omits empties", () => {
    expect(
      serializeProvparningParams({
        genebank: 1,
        hona: "G1274-2112",
        hane: ["G1274-2201", "G1301-2104"],
      }),
    ).toBe("genebank=1&hona=G1274-2112&hane=G1274-2201&hane=G1301-2104");
    expect(
      serializeProvparningParams({ genebank: null, hona: null, hane: [] }),
    ).toBe("");
  });
  it("round-trips", () => {
    const p = { genebank: 2, hona: "M3-1", hane: ["M3-2", "M3-3"] };
    const qs = new URLSearchParams(serializeProvparningParams(p));
    expect(
      parseProvparningParams({
        genebank: qs.get("genebank")!,
        hona: qs.get("hona")!,
        hane: qs.getAll("hane"),
      }),
    ).toEqual(p);
  });
  it("parses a query string or URLSearchParams the same way", () => {
    const qs = "genebank=1&hona=G1-1&hane=G1-2&hane=G1-3&hane=G1-2";
    const expected = { genebank: 1, hona: "G1-1", hane: ["G1-2", "G1-3"] };
    expect(paramsFromSearch(qs)).toEqual(expected);
    expect(paramsFromSearch(`?${qs}`)).toEqual(expected);
    expect(paramsFromSearch(new URLSearchParams(qs))).toEqual(expected);
    expect(paramsFromSearch("")).toEqual({
      genebank: null,
      hona: null,
      hane: [],
    });
  });
});

describe("effectiveSelection", () => {
  // The server rendered ?hona=G1-1&hane=G1-2&hane=G9-9 (no genebank): G9-9 is
  // not visible, the genebank came from the female.
  const server = {
    query: serializeProvparningParams({
      genebank: null,
      hona: "G1-1",
      hane: ["G1-2", "G9-9"],
    }),
    selection: { genebank: 1, hona: "G1-1", hane: ["G1-2"] },
  };

  it("uses the server's resolved selection for the URL it rendered", () => {
    expect(
      effectiveSelection(
        paramsFromSearch("hane=G1-2&hona=G1-1&hane=G9-9"),
        server,
        [1, 2],
      ),
    ).toEqual(server.selection);
  });

  it("takes any other URL as is", () => {
    expect(
      effectiveSelection(
        paramsFromSearch("genebank=2&hona=M2-1&hane=M2-2"),
        server,
        [1, 2],
      ),
    ).toEqual({ genebank: 2, hona: "M2-1", hane: ["M2-2"] });
  });

  it("falls back to the server's genebank for an unknown one", () => {
    expect(
      effectiveSelection(
        paramsFromSearch("genebank=7&hona=G1-5"),
        server,
        [1, 2],
      ).genebank,
    ).toBe(1);
  });
});

describe("replaceMale", () => {
  it("picking the slot's own male again changes nothing", () => {
    // MUI reports a change: the prefilled item and the search hit are
    // different objects for the same male.
    const hane = ["A", "B"];
    expect(replaceMale(hane, "A", "A")).toBe(hane);
    expect(replaceMale([], null, null)).toEqual([]);
  });
  it("appends a pick in an empty slot", () => {
    expect(replaceMale(["A"], null, "B")).toEqual(["A", "B"]);
  });
  it("replaces in place", () => {
    expect(replaceMale(["A", "B", "C"], "B", "D")).toEqual(["A", "D", "C"]);
  });
  it("removes a cleared or removed male", () => {
    expect(replaceMale(["A", "B"], "A", null)).toEqual(["B"]);
  });
  it("never adds a male twice", () => {
    expect(replaceMale(["A", "B"], null, "A")).toEqual(["A", "B"]);
    // Picking an already chosen male in another filled slot clears that slot.
    expect(replaceMale(["A", "B"], "B", "A")).toEqual(["A"]);
  });
  it("leaves the list alone for a number it does not have", () => {
    const hane = ["A"];
    expect(replaceMale(hane, "X", null)).toBe(hane);
  });
});

describe("deriveMaleSlots", () => {
  const reg = (key: string, number: string): Slot => ({
    ...emptySlot(key),
    number,
  });
  const unreg = (key: string, number: string | null = null): Slot => ({
    ...emptySlot(key),
    number,
    unregistered: true,
    father: picked("G1-F"),
  });

  it("builds slots from the URL alone", () => {
    expect(deriveMaleSlots([], ["A", "B"])).toEqual([
      reg("hane:A", "A"),
      reg("hane:B", "B"),
    ]);
  });

  it("always shows at least one (empty) slot", () => {
    expect(deriveMaleSlots([], [])).toEqual([emptySlot("hane")]);
  });

  it("keeps the layout for males the URL still has, in layout order", () => {
    const slots = [reg("k2", "B"), emptySlot("k3"), reg("k1", "A")];
    expect(deriveMaleSlots(slots, ["A", "B"])).toEqual(slots);
  });

  it("the URL wins: a male it no longer has disappears, a new one is appended", () => {
    expect(
      deriveMaleSlots([reg("k1", "A"), reg("k2", "B")], ["B", "C"]),
    ).toEqual([reg("k2", "B"), reg("hane:C", "C")]);
  });

  it("keeps unregistered slots (their remembered pick is not in the URL)", () => {
    const slots = [unreg("k1", "A"), reg("k2", "B")];
    expect(deriveMaleSlots(slots, ["B", "A"])).toEqual([
      unreg("k1", "A"),
      reg("k2", "B"),
      reg("hane:A", "A"),
    ]);
  });

  it("shows a male once even if two slots name it", () => {
    expect(deriveMaleSlots([reg("k1", "A"), reg("k2", "A")], ["A"])).toEqual([
      reg("k1", "A"),
    ]);
  });

  it("never reuses a key", () => {
    // A slot first made for A (key hane:A) that now holds B.
    const keys = deriveMaleSlots([reg("hane:A", "B")], ["B", "A"]).map(
      (s) => s.key,
    );
    expect(new Set(keys).size).toBe(keys.length);
  });
});

describe("layoutFor / editLayout", () => {
  const reg = (key: string, number: string): Slot => ({
    ...emptySlot(key),
    number,
  });
  // Slot k2 was added empty, then Storm was picked in it: URL q1 -> q2.
  const before = {
    ...EMPTY_LAYOUT,
    query: "q1",
    slots: [reg("k1", "A"), emptySlot("k2")],
  };
  const after = editLayout(before, "q1", "q2", ["A"], (all) =>
    all.map((s) => (s.key === "k2" ? { ...s, number: "S" } : s)),
  );

  it("records the edit for the URL it wrote", () => {
    expect(layoutFor(after, "q2")).toEqual([reg("k1", "A"), reg("k2", "S")]);
  });

  it("shows the layout from before the edit while the URL has not caught up", () => {
    expect(layoutFor(after, "q1")).toEqual([reg("k1", "A"), emptySlot("k2")]);
  });

  it("gives any other URL (a navigation) the latest layout", () => {
    expect(layoutFor(after, "elsewhere")).toBe(after.slots);
  });

  it("an edit that writes nothing keeps one layout", () => {
    const added = editLayout(after, "q2", "q2", ["A", "S"], (all) => [
      ...all,
      emptySlot("k3"),
    ]);
    expect(layoutFor(added, "q2").map((s) => s.key)).toEqual([
      "k1",
      "k2",
      "k3",
    ]);
  });

  it("two quick edits chain on the browser URL, not the rendered one", () => {
    // Remove A while the router still renders q1: starts from q2's layout.
    const removed = editLayout(after, "q2", "q3", ["A", "S"], (all) =>
      all.filter((s) => s.key !== "k1"),
    );
    expect(layoutFor(removed, "q3")).toEqual([reg("k2", "S")]);
    expect(layoutFor(removed, "q2")).toEqual([reg("k1", "A"), reg("k2", "S")]);
  });
});

describe("slotNow", () => {
  const reg = (key: string, number: string): Slot => ({
    ...emptySlot(key),
    number,
  });

  it("two picks in one slot before the router renders: the second replaces the first", () => {
    // Slot hane:A (from the URL) gets B, then C, in the same task.
    const first = slotNow(EMPTY_LAYOUT, "q0", ["A"], "hane:A")!;
    expect(first.number).toBe("A");
    const hane1 = replaceMale(["A"], first.number, "B");
    const l1 = editLayout(EMPTY_LAYOUT, "q0", "q1", ["A"], (all) =>
      all.map((s) => (s.key === "hane:A" ? { ...s, number: "B" } : s)),
    );
    // The second handler reads the URL the first one wrote (q1, [B]).
    const second = slotNow(l1, "q1", hane1, "hane:A")!;
    expect(second.number).toBe("B");
    expect(replaceMale(hane1, second.number, "C")).toEqual(["C"]);
  });

  it("is undefined for a slot removed by an earlier edit", () => {
    const l1 = editLayout(
      { ...EMPTY_LAYOUT, query: "q0", slots: [reg("k1", "A"), reg("k2", "B")] },
      "q0",
      "q1",
      ["A", "B"],
      (all) => all.filter((s) => s.key !== "k1"),
    );
    expect(slotNow(l1, "q1", ["B"], "k1")).toBeUndefined();
  });
});

describe("settleLayout", () => {
  const unreg: Slot = {
    ...emptySlot("k"),
    number: "A",
    unregistered: true,
    father: picked("G1-F"),
  };

  it("retires the pre-write layout once the URL reached the write", () => {
    // Unregistered (q0) -> registered A (q1) -> unregistered again (q2).
    const atQ0 = { ...EMPTY_LAYOUT, query: "q0", slots: [unreg] };
    const atQ1 = editLayout(atQ0, "q0", "q1", [], (all) =>
      all.map((s) => ({ ...s, unregistered: false })),
    );
    const atQ2 = editLayout(atQ1, "q1", "q2", ["A"], (all) =>
      all.map((s) => ({ ...s, unregistered: true })),
    );
    // Pending: the URL still reads q1, show the layout from before.
    expect(layoutFor(atQ2, "q1")[0].unregistered).toBe(false);
    // The router reached q2; a later navigation to q1 is not that write.
    const settled = settleLayout(atQ2, "q2", "q2");
    expect(settled.before).toBeNull();
    expect(layoutFor(settled, "q1")).toEqual([unreg]);
    expect(deriveMaleSlots(layoutFor(settled, "q1"), ["A"])).toEqual([
      unreg,
      { ...emptySlot("hane:A"), number: "A" },
    ]);
  });

  it("leaves a pending write alone", () => {
    const pending = editLayout(EMPTY_LAYOUT, "q0", "q1", [], (all) => all);
    expect(settleLayout(pending, "q0", "q1")).toBe(pending);
    // A later write is pending even if the router reached an earlier one.
    const next = editLayout(pending, "q1", "q2", [], (all) => all);
    expect(settleLayout(next, "q1", "q2")).toBe(next);
  });

  it("retires when the browser is back at the URL before an unseen write", () => {
    // Male edit q0 -> q1 that the router never commits: a navigation to q0
    // in the same transition supersedes it, so the router only shows q0.
    const atQ1 = editLayout(EMPTY_LAYOUT, "q0", "q1", [], (all) => all);
    expect(settleLayout(atQ1, "q0", "q1")).toBe(atQ1);
    const settled = settleLayout(atQ1, "q0", "q0");
    expect(settled.before).toBeNull();
    expect(layoutFor(settled, "q0")).toBe(settled.slots);
  });

  it("retires when a later URL supersedes the write before it is seen", () => {
    // Male edit q0 -> q1, then (same task) a female edit writes q2 without
    // touching the layout; the router only ever renders q2.
    const atQ1 = editLayout(EMPTY_LAYOUT, "q0", "q1", [], (all) => all);
    const settled = settleLayout(atQ1, "q2", "q2");
    expect(settled.before).toBeNull();
    // A later navigation back to q0 shows the current layout, not the base.
    expect(layoutFor(settled, "q0")).toBe(settled.slots);
  });

  it("an edit that writes nothing has nothing pending", () => {
    expect(editLayout(EMPTY_LAYOUT, "q0", "q0", [], (all) => all).before).toBe(
      null,
    );
  });
});

describe("withDetails", () => {
  it("adds items by number and ignores nulls", () => {
    const a = picked("G1-1");
    const map = withDetails(new Map(), [a, null]);
    expect([...map.entries()]).toEqual([["G1-1", a]]);
  });
  it("returns the same map when nothing is new", () => {
    const a = picked("G1-1");
    const map = withDetails(new Map(), [a]);
    expect(withDetails(map, [a, null])).toBe(map);
  });
  it("lets a later item for the same number win", () => {
    const stubbed = picked("G1-1");
    const named = { ...picked("G1-1"), name: "Visby Vilda" };
    expect(
      withDetails(withDetails(new Map(), [stubbed]), [named]).get("G1-1"),
    ).toBe(named);
  });
});

describe("tooManyMales", () => {
  const req = (n: number) => ({
    genebank_id: 1,
    female: "G1-1",
    males: Array.from({ length: n }, (_, i) => ({ number: `G1-${i + 2}` })),
  });
  it("allows up to MAX_MALES comparisons", () => {
    expect(tooManyMales(null)).toBe(false);
    expect(tooManyMales(req(MAX_MALES))).toBe(false);
  });
  it("flags one more, e.g. ten registered plus a local unregistered male", () => {
    const female = animal({ picked: picked("G1-1", "female") });
    const males = [
      ...Array.from({ length: 10 }, (_, i) =>
        animal({ picked: picked(`G1-${i + 2}`) }),
      ),
      animal({ unregistered: true, father: picked("G1-F") }),
    ];
    expect(tooManyMales(buildTestbreedRequest(1, female, males))).toBe(true);
    expect(tooManyMales(req(MAX_MALES + 1))).toBe(true);
  });
});

describe("buildTestbreedRequest", () => {
  it("is null until a female and a male are chosen", () => {
    expect(buildTestbreedRequest(1, animal(), [animal()])).toBeNull();
    expect(
      buildTestbreedRequest(1, animal({ picked: picked("G1-1", "female") }), [
        animal(),
      ]),
    ).toBeNull();
    expect(
      buildTestbreedRequest(null, animal({ picked: picked("G1-1") }), [
        animal({ picked: picked("G1-2") }),
      ]),
    ).toBeNull();
  });
  it("builds a registered pair and skips empty male slots", () => {
    expect(
      buildTestbreedRequest(1, animal({ picked: picked("G1-1", "female") }), [
        animal({ picked: picked("G1-2") }),
        animal(),
        animal({ picked: picked("G1-3") }),
      ]),
    ).toEqual({
      genebank_id: 1,
      female: "G1-1",
      males: [{ number: "G1-2" }, { number: "G1-3" }],
    });
  });
  it("uses the stated parents for an unregistered animal", () => {
    const req = buildTestbreedRequest(
      1,
      animal({ unregistered: true, mother: picked("G1-M", "female") }),
      [
        animal({
          unregistered: true,
          mother: picked("G1-A", "female"),
          father: picked("G1-B"),
        }),
      ],
    );
    expect(req).toEqual({
      genebank_id: 1,
      female: null,
      female_parents: { mother: "G1-M", father: null },
      males: [{ number: null, parents: { mother: "G1-A", father: "G1-B" } }],
    });
  });
  it("ignores the registered pick while the unregistered toggle is on", () => {
    expect(
      buildTestbreedRequest(
        1,
        animal({ picked: picked("G1-1", "female"), unregistered: true }),
        [animal({ picked: picked("G1-2") })],
      ),
    ).toBeNull();
  });
});

describe("sortResults", () => {
  it("sorts by F ascending and keeps the original index; ties keep order", () => {
    const sorted = sortResults([
      { offspring_f: 12.5 },
      { offspring_f: 0 },
      { offspring_f: 12.5 },
      { offspring_f: 3.1 },
    ]);
    expect(sorted.map((s) => s.index)).toEqual([1, 3, 0, 2]);
  });
});

describe("describeGenerations", () => {
  it("describes distance from each side", () => {
    expect(describeGenerations([2, 1])).toBe(
      "2 led från hanen, 1 led från honan",
    );
    expect(describeGenerations([0, 1])).toBe(
      "är hanen själv, 1 led från honan",
    );
  });
});

describe("createSequence", () => {
  it("only the most recent invocation is current (A -> B -> A)", () => {
    const seq = createSequence();
    const firstA = seq.next();
    const b = seq.next();
    const secondA = seq.next();
    expect(seq.isLatest(firstA)).toBe(false);
    expect(seq.isLatest(b)).toBe(false);
    expect(seq.isLatest(secondA)).toBe(true);
  });

  it("a later invocation supersedes an in-flight one even for the same input", () => {
    const seq = createSequence();
    const a = seq.next();
    expect(seq.isLatest(a)).toBe(true);
    seq.next();
    expect(seq.isLatest(a)).toBe(false);
  });
});
