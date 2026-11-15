import { describe, expect, it } from "vitest";
import {
  callFrom,
  countByState,
  filterRows,
  parseFilter,
  type RowState,
  type StatusRow,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

const row = (
  herd: string,
  state: RowState,
  over: Partial<StatusRow> = {},
): StatusRow => ({
  herd,
  herd_name: null,
  state,
  source: null,
  membership_after_end: null,
  received_at: null,
  on_time_override: null,
  inbox_item_id: null,
  flags: { ej_angivna: 0, ej_angivna_paverkar: false },
  villkor: { hane: false, hona: false, kull: false, i_tid: false },
  statistik: { kullar: 0, ungar: 0, levande_6v: 0, honor: 0, hanar: 0 },
  ...over,
});

const rows = [
  row("G9001", "paborjad"),
  row("G9002", "paborjad"),
  row("G9003", "ej_rapporterad"),
  row("G9004", "ingen_epost"),
  row("G9005", "inskickad", { received_at: "2027-01-10T09:00:00+01:00" }),
  row("G9006", "blankett_inkommen"),
  row("G9007", "inskickad", {
    received_at: "2027-01-12T09:00:00+01:00",
    flags: { ej_angivna: 3, ej_angivna_paverkar: true },
  }),
  row("G9008", "inskickad", {
    flags: { ej_angivna: 1, ej_angivna_paverkar: false },
  }),
];
const herds = (list: StatusRow[]) => list.map((r) => r.herd);

describe("status view filters", () => {
  it("counts the rows per state", () => {
    expect(countByState(rows)).toEqual({
      avslutar: 0,
      inskickad: 3,
      blankett_vantar: 0,
      blankett_inkommen: 1,
      paborjad: 2,
      ingen_epost: 1,
      ej_rapporterad: 1,
    });
  });
  it("filters on a state, and Alla keeps every row", () => {
    expect(
      herds(filterRows(rows, "paborjad", "2027-01-31", "2027-01-01")),
    ).toEqual(["G9001", "G9002"]);
    expect(filterRows(rows, "avslutar", "2027-01-31", "2027-01-01")).toEqual(
      [],
    );
    expect(filterRows(rows, "alla", "2027-01-31", "2027-01-01")).toHaveLength(
      8,
    );
  });
  it("reads the filter from the URL and falls back to Alla", () => {
    expect(parseFilter("att_ringa")).toBe("att_ringa");
    expect(parseFilter("paborjad")).toBe("paborjad");
    expect(parseFilter("x")).toBe("alla");
    expect(parseFilter(undefined)).toBe("alla");
  });
});

describe("Att ringa", () => {
  it("starts two days before the deadline", () => {
    expect(callFrom("2027-01-31")).toBe("2027-01-29");
    expect(callFrom("2027-02-07")).toBe("2027-02-05");
    expect(callFrom("2027-03-01")).toBe("2027-02-27");
  });
  it("is the herds nobody reported for from deadline minus 2 days, and the herds whose omitted rabbits decide the support", () => {
    // Before the boundary only the support-affecting herd.
    expect(
      herds(filterRows(rows, "att_ringa", "2027-01-31", "2027-01-28")),
    ).toEqual(["G9007"]);
    // On the boundary, 29 January for the deadline 31 January.
    expect(
      herds(filterRows(rows, "att_ringa", "2027-01-31", "2027-01-29")),
    ).toEqual(["G9001", "G9002", "G9003", "G9004", "G9007"]);
  });
  it("follows a moved deadline", () => {
    expect(
      filterRows(rows, "att_ringa", "2027-02-07", "2027-01-29"),
    ).toHaveLength(1);
    expect(
      filterRows(rows, "att_ringa", "2027-02-07", "2027-02-04"),
    ).toHaveLength(1);
    expect(
      filterRows(rows, "att_ringa", "2027-02-07", "2027-02-05"),
    ).toHaveLength(5);
  });
  it("leaves a round without a deadline to the support flag", () => {
    expect(herds(filterRows(rows, "att_ringa", null, "2027-12-31"))).toEqual([
      "G9007",
    ]);
  });
});
