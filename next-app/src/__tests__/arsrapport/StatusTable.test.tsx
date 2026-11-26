import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock("@/lib/mode-context", () => ({ useMode: () => "demo" }));
const newLink = vi.fn();
const saleProposals = vi.fn();
const undoAccountLink = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/arsrapport/actions", () => ({
  setOnTime: vi.fn(),
  newLink: (...a: unknown[]) => newLink(...a),
  undoAccountLink: (...a: unknown[]) => undoAccountLink(...a),
  saleProposals: (...a: unknown[]) => saleProposals(...a),
  approveSale: vi.fn(),
  rejectSale: vi.fn(),
}));

import {
  BlankFormLink,
  StatusTable,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/status/[year]/StatusTable";
import type {
  StatusRow,
  StatusView,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(() => {
  cleanup();
  newLink.mockReset();
  saleProposals.mockReset();
});

const NO_SALES = {
  forsaljning_vantar: 0,
  forsaljning_avvisad: 0,
  forsaljning_avvisad_paverkar: false,
  kopt_efter_inskick: 0,
  kop_anmalt: 0,
};

const base: StatusRow = {
  herd: "G9001",
  herd_name: "Gård",
  state: "paborjad",
  inbjudan: null,
  ingen_epost: false,
  source: null,
  membership_after_end: null,
  received_at: null,
  on_time_override: null,
  inbox_item_id: null,
  flags: { ej_angivna: 0, ej_angivna_paverkar: false, ...NO_SALES },
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
  flags: { ej_angivna: 3, ej_angivna_paverkar: true, ...NO_SALES },
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
  it("offers Mata in blankett only on rows that are not submitted", () => {
    show(true);
    expect(
      within(screen.getByText("G9002").closest("tr")!).queryByText(
        "Mata in blankett",
      ),
    ).toBeNull();
    expect(
      within(screen.getByText("G9001").closest("tr")!).getByText(
        "Mata in blankett",
      ),
    ).toBeTruthy();
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
  it("shows a tel link only on a row with a phone", () => {
    render(
      <StatusTable
        view={view([base, { ...sent, telefon: "070-000 00 00" }])}
        year={2026}
        genebankId={1}
        filter="alla"
        canEdit
        env="demo"
      />,
    );
    const phone = screen.getByText("070-000 00 00");
    expect(phone.getAttribute("href")).toBe("tel:0700000000");
    expect(document.querySelectorAll('a[href^="tel:"]')).toHaveLength(1);
  });
  it("gives each of two numbers in the phone field its own tel link", () => {
    render(
      <StatusTable
        view={view([{ ...sent, telefon: "08 - 510 122 07 0709 - 55 72 08" }])}
        year={2026}
        genebankId={1}
        filter="alla"
        canEdit
        env="demo"
      />,
    );
    const links = [...document.querySelectorAll('a[href^="tel:"]')];
    expect(links.map((a) => a.getAttribute("href"))).toEqual([
      "tel:0851012207",
      "tel:0709557208",
    ]);
  });
  it("says the blank form is missing instead of linking to a 404", () => {
    render(<BlankFormLink available={false} />);
    expect(
      screen.getByText("Den tomma blanketten finns inte på servern än."),
    ).toBeTruthy();
    expect(screen.queryByText("Skriv ut tom blankett")).toBeNull();
  });
  it("shows no payment control", () => {
    show(true);
    expect(document.body.textContent).not.toMatch(/Nordea|pain|betalning/i);
  });
  it("shows the invitation state of each row", () => {
    const states = [
      ["skickad", "Inbjudan skickad"],
      ["studsade", "Inbjudan studsade"],
      ["misslyckades", "Inbjudan misslyckades"],
      ["oppnad", "Länken öppnad"],
    ] as const;
    render(
      <StatusTable
        view={view(
          states.map(([inbjudan], i) => ({
            ...base,
            herd: `G910${i}`,
            inbjudan,
          })),
        )}
        year={2026}
        genebankId={1}
        filter="alla"
        canEdit
        env="demo"
      />,
    );
    states.forEach(([, text], i) =>
      expect(
        within(screen.getByText(`G910${i}`).closest("tr")!).getByText(text),
      ).toBeTruthy(),
    );
  });
  it("flags a herd without e-mail beside a state that is not ingen_epost, and offers no Ny länk", () => {
    render(
      <StatusTable
        view={view([{ ...base, ingen_epost: true }])}
        year={2026}
        genebankId={1}
        filter="alla"
        canEdit
        env="demo"
      />,
    );
    const tr = screen.getByText("G9001").closest("tr")!;
    expect(within(tr).getByText("Ingen e-post")).toBeTruthy();
    expect(within(tr).queryByText("Ny länk")).toBeNull();
  });
  it("asks before it sends a new link, and sends only on yes", async () => {
    newLink.mockResolvedValue({ ok: true, data: { sent: true } });
    show(true);
    fireEvent.click(
      within(screen.getByText("G9001").closest("tr")!).getByText("Ny länk"),
    );
    expect(
      screen.getByText(
        "Den gamla länken slutar gälla. Skicka en ny länk till huvudmedlemmen?",
      ),
    ).toBeTruthy();
    expect(newLink).not.toHaveBeenCalled();
    fireEvent.click(screen.getByText("Skicka ny länk"));
    await waitFor(() =>
      expect(newLink).toHaveBeenCalledWith("G9001", 2026, "demo"),
    );
  });
  it("shows the link's change flags without values, and Koppla bort asks first (5.1, 5.14)", async () => {
    undoAccountLink.mockResolvedValue({ ok: true, data: { ok: true } });
    const flagged: StatusRow = {
      ...sent,
      flags: {
        ...sent.flags,
        andring_vantar: 2,
        kontobyte_vantar: false,
        kontobyte_forfoll: true,
        inte_jag: true,
        nytt_konto: 41,
      },
    };
    const props = {
      year: 2026,
      genebankId: 1,
      filter: "alla" as const,
      env: "demo" as const,
    };
    const { unmount } = render(
      <StatusTable {...props} view={view([flagged])} canEdit={false} />,
    );
    for (const text of [
      "Ändring väntar på bekräftelse",
      "Kontobyte förföll",
      "Det var inte jag",
      "Nytt konto",
    ])
      expect(screen.getByText(text)).toBeTruthy();
    expect(screen.queryByText("Kontobyte väntar på bekräftelse")).toBeNull();
    expect(screen.queryByText("Koppla bort kontot")).toBeNull(); // a helper sees, but does not undo
    unmount();
    render(<StatusTable {...props} view={view([flagged])} canEdit />);
    fireEvent.click(screen.getByText("Koppla bort kontot"));
    expect(screen.getByText(/Andra behörigheter påverkas inte\./)).toBeTruthy();
    expect(undoAccountLink).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Koppla bort" }));
    await waitFor(() =>
      expect(undoAccountLink).toHaveBeenCalledWith(41, "demo"),
    );
  });
  it("offers Ny länk only to a manager", () => {
    show(false);
    expect(screen.queryByText("Ny länk")).toBeNull();
  });

  it("flags a preliminary count, and not a confirmed one", () => {
    const row = (preliminart: boolean): StatusRow => ({
      ...sent,
      flags: { ...sent.flags, ej_angivna: 0, ej_angivna_paverkar: false },
      statistik: { ...base.statistik, preliminart },
    });
    const table = (preliminart: boolean) => (
      <StatusTable
        view={view([row(preliminart)])}
        year={2026}
        genebankId={1}
        filter="alla"
        canEdit={false}
        env="demo"
      />
    );
    const { unmount } = render(table(true));
    expect(screen.getByText("Preliminärt antal")).toBeTruthy();
    unmount();
    render(table(false));
    expect(screen.queryByText("Preliminärt antal")).toBeNull();
  });
  it("shows the sale flags, and Försäljningar opens the herd's proposals for a manager", async () => {
    saleProposals.mockResolvedValue({ ok: true, data: { forslag: [] } });
    const flags = {
      ...sent.flags,
      forsaljning_vantar: 2,
      forsaljning_avvisad: 1,
      forsaljning_avvisad_paverkar: true,
      kopt_efter_inskick: 1,
    };
    const shown = (canEdit: boolean) =>
      render(
        <StatusTable
          view={view([{ ...sent, flags }])}
          year={2026}
          genebankId={1}
          filter="alla"
          canEdit={canEdit}
          env="demo"
        />,
      );
    shown(false);
    expect(screen.getByText("2 försäljningar väntar")).toBeTruthy();
    expect(
      screen.getByText(/Försäljning avvisad, medlemmen väljer igen/)
        .textContent,
    ).toContain("(påverkar stödet)");
    expect(screen.getByText("Köpt efter inskick")).toBeTruthy();
    expect(screen.queryByText("Försäljningar")).toBeNull(); // a helper decides nothing
    cleanup();
    shown(true);
    fireEvent.click(screen.getByText("Försäljningar"));
    await waitFor(() =>
      expect(saleProposals).toHaveBeenCalledWith("G9002", 2026, "demo"),
    );
    expect(await screen.findByText("Inga försäljningar väntar.")).toBeTruthy();
  });
});
