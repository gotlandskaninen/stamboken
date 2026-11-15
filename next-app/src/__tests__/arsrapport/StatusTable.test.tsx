import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/mode-context", () => ({ useMode: () => "demo" }));
vi.mock("@/app/(app)/stamboken/(dashboard)/arsrapport/actions", () => ({
  setOnTime: vi.fn(),
}));

import { StatusTable } from "@/app/(app)/stamboken/(dashboard)/arsrapport/status/[year]/StatusTable";
import type {
  StatusRow,
  StatusView,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(cleanup);

const base: StatusRow = {
  herd: "G9001",
  herd_name: "Gård",
  state: "paborjad",
  source: null,
  membership_after_end: null,
  received_at: null,
  on_time_override: null,
  inbox_item_id: null,
  flags: { ej_angivna: 0, ej_angivna_paverkar: false },
  villkor: { hane: true, hona: true, kull: false, i_tid: true },
  statistik: { kullar: 0, ungar: 0, levande_6v: 0, honor: 0, hanar: 0 },
};
const view = (rows: StatusRow[]): StatusView => ({
  round: {
    year: 2026,
    start_date: "2026-12-31",
    deadline: "2027-01-31",
    end_date: "2027-03-01",
    is_active: true,
    genebanks: [],
  },
  genebank_id: 1,
  activated: true,
  counts: {} as StatusView["counts"],
  rows,
});
const sent: StatusRow = {
  ...base,
  herd: "G9002",
  state: "inskickad",
  source: "paper",
  received_at: "2027-01-10T09:00:00+01:00",
  flags: { ej_angivna: 3, ej_angivna_paverkar: true },
};
const show = (canEdit: boolean) =>
  render(
    <StatusTable
      view={view([base, sent])}
      year={2026}
      genebankId={1}
      filter="alla"
      canEdit={canEdit}
      env="demo"
    />,
  );

describe("StatusTable", () => {
  it("shows conditions and I tid only on a row with a report", () => {
    show(true);
    const open = screen.getByText("G9001").closest("tr")!;
    expect(within(open).queryByText("Hane")).toBeNull();
    expect(within(open).queryByLabelText(/I tid/)).toBeNull();
    const done = screen.getByText("G9002").closest("tr")!;
    expect(within(done).getByText("Kull")).toBeTruthy();
    expect(within(done).getByLabelText(/I tid/)).toBeTruthy();
    expect(within(done).getByText(/3 ej angivna/)).toBeTruthy();
  });
  it("hides I tid for a helper", () => {
    show(false);
    expect(screen.queryByLabelText(/I tid/)).toBeNull();
  });
  it("links each herd to its report and the form entry to the queue", () => {
    show(true);
    expect(screen.getByText("G9002").getAttribute("href")).toBe(
      "/stamboken/arsrapport/G9002/2026",
    );
    expect(
      screen.getAllByText("Mata in blankett")[0].getAttribute("href"),
    ).toBe("/stamboken/inkorg?herd=G9001");
  });
  it("shows no payment control", () => {
    show(true);
    expect(document.body.textContent).not.toMatch(/Nordea|pain|betalning/i);
  });
});
