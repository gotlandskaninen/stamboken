import { describe, expect, it } from "vitest";
import {
  callFrom,
  countByState,
  currentRoundYear,
  defaultRoundDates,
  phoneNumbers,
  regularRoundYear,
  filterRows,
  parseFilter,
  toCall,
  ROW_STATES,
  type Round,
  type RowState,
  type StatusRow,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

const NO_SALES = {
  forsaljning_vantar: 0,
  forsaljning_avvisad: 0,
  forsaljning_avvisad_paverkar: false,
  kopt_efter_inskick: 0,
  kop_anmalt: 0,
};

const row = (
  herd: string,
  state: RowState,
  over: Partial<StatusRow> = {},
): StatusRow => ({
  herd,
  herd_name: null,
  state,
  inbjudan: null,
  ingen_epost: false,
  source: null,
  membership_after_end: null,
  received_at: null,
  on_time_override: null,
  inbox_item_id: null,
  flags: { ej_angivna: 0, ej_angivna_paverkar: false, ...NO_SALES },
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
    flags: { ej_angivna: 3, ej_angivna_paverkar: true, ...NO_SALES },
  }),
  row("G9008", "inskickad", {
    flags: { ej_angivna: 1, ej_angivna_paverkar: false, ...NO_SALES },
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
  it.each([
    "avslutar",
    "inskickad",
    "blankett_vantar",
    "blankett_inkommen",
    "paborjad",
    "ingen_epost",
    "ej_rapporterad",
  ] as const)("filters on the state %s", (state) => {
    const list = ROW_STATES.map((s, i) => row(`G90${i}`, s));
    expect(
      filterRows(list, state, "2027-01-31", "2027-01-01").map((r) => r.state),
    ).toEqual([state]);
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
  it("is started drafts from deadline minus 2 days, and the herds whose omitted rabbits decide the support", () => {
    // Before the boundary only the support-affecting herd.
    expect(
      herds(filterRows(rows, "att_ringa", "2027-01-31", "2027-01-28")),
    ).toEqual(["G9007"]);
    // On the boundary, 29 January for the deadline 31 January.
    expect(
      herds(filterRows(rows, "att_ringa", "2027-01-31", "2027-01-29")),
    ).toEqual(["G9001", "G9002", "G9007"]);
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
    ).toHaveLength(3);
  });
  it("leaves a round without a deadline to the support flag", () => {
    expect(herds(filterRows(rows, "att_ringa", null, "2027-12-31"))).toEqual([
      "G9007",
    ]);
  });
});

describe("toCall and a rejected sale", () => {
  it("calls a herd whose rabbit to choose again decides the support (FB3)", () => {
    const flags = (paverkar: boolean) => ({
      ej_angivna: 0,
      ej_angivna_paverkar: false,
      ...NO_SALES,
      forsaljning_avvisad: 1,
      forsaljning_avvisad_paverkar: paverkar,
    });
    const sent = { received_at: "2027-01-10T09:00:00+01:00" };
    expect(
      toCall(
        row("G9001", "inskickad", { ...sent, flags: flags(true) }),
        null,
        "2027-01-01",
      ),
    ).toBe(true);
    expect(
      toCall(
        row("G9001", "inskickad", { ...sent, flags: flags(false) }),
        null,
        "2027-01-01",
      ),
    ).toBe(false);
  });
});

describe("toCall and a failed invitation", () => {
  it("calls a herd whose invitation bounced or failed, until it has reported", () => {
    const today = "2027-01-01";
    expect(
      toCall(
        row("G9001", "ej_rapporterad", { inbjudan: "studsade" }),
        null,
        today,
      ),
    ).toBe(true);
    expect(
      toCall(
        row("G9001", "ej_rapporterad", { inbjudan: "misslyckades" }),
        null,
        today,
      ),
    ).toBe(true);
    expect(
      toCall(row("G9001", "inskickad", { inbjudan: "studsade" }), null, today),
    ).toBe(false);
    expect(
      toCall(row("G9001", "avslutar", { inbjudan: "studsade" }), null, today),
    ).toBe(false);
    expect(
      toCall(
        row("G9001", "ej_rapporterad", { inbjudan: "skickad" }),
        null,
        today,
      ),
    ).toBe(false);
  });
});

describe("phoneNumbers", () => {
  it("splits a field with two numbers so each can be dialled", () => {
    expect(phoneNumbers("08 - 510 122 07 0709 - 55 72 08")).toEqual([
      "08 - 510 122 07",
      "0709 - 55 72 08",
    ]);
  });
  it("keeps one number whole, with or without a dash", () => {
    expect(phoneNumbers("0761 13 39 05")).toEqual(["0761 13 39 05"]);
    expect(phoneNumbers("070-000 00 01")).toEqual(["070-000 00 01"]);
    expect(phoneNumbers("0730601951")).toEqual(["0730601951"]);
  });
  it("keeps a piece too short to be a number with the next one", () => {
    for (const one of [
      "+46 70-123 45 67",
      "070 123 45-67",
      "0498 12-34-56",
      "Mobil 070-1234567",
      "+46 70 123 45-67",
      "+46 70 123 04-56",
    ])
      expect(phoneNumbers(one)).toEqual([one]);
  });
});

describe("currentRoundYear", () => {
  const round = (
    year: number,
    end_date: string | null,
    start_date: string | null = `${year}-12-31`,
  ): Round => ({
    year,
    start_date,
    deadline: null,
    end_date,
    is_active: false,
    genebanks: [],
  });
  it("is last year's round until it closes", () => {
    expect(currentRoundYear([round(2026, "2027-03-30")], "2027-02-01")).toBe(
      2026,
    );
  });
  it("is this year's once last year's has closed, even before it exists", () => {
    expect(currentRoundYear([round(2025, "2026-03-30")], "2026-11-25")).toBe(
      2026,
    );
    expect(currentRoundYear([], "2026-11-25")).toBe(2026);
  });
  it("is an older round that is still open, whatever the year", () => {
    expect(currentRoundYear([round(2025, "2027-01-24")], "2027-01-01")).toBe(
      2025,
    );
  });
  it("is not a round prepared for later, and the switch keeps the regular year", () => {
    const later = [round(2027, "2028-03-30")];
    expect(currentRoundYear(later, "2027-01-15")).toBe(2026);
    expect(regularRoundYear(later, "2027-01-15")).toBe(2026);
  });
  it("is last year's until its default close when it does not exist yet", () => {
    expect(currentRoundYear([round(2025, "2026-03-30")], "2027-01-15")).toBe(
      2026,
    );
  });
  it("gives the server's default dates for a new round", () => {
    expect(defaultRoundDates(2026)).toEqual({
      start_date: "2026-12-31",
      deadline: "2027-01-31",
      end_date: "2027-03-30",
    });
  });
});
