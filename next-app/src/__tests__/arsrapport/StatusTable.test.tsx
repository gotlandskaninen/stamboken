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

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));
vi.mock("@/lib/mode-context", () => ({ useMode: () => "demo" }));
const newLink = vi.fn();
const sendReminder = vi.fn();
const saleProposals = vi.fn();
const undoAccountLink = vi.fn();
vi.mock("@/app/(app)/stamboken/(dashboard)/arsrapport/actions", () => ({
  setOnTime: vi.fn(),
  newLink: (...a: unknown[]) => newLink(...a),
  sendReminder: (...a: unknown[]) => sendReminder(...a),
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
  StatusFilter,
  StatusRow,
  StatusView,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(() => {
  cleanup();
  refresh.mockClear();
  newLink.mockReset();
  sendReminder.mockReset();
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
  needs_report: true,
  inbjudan: "oppnad",
  report_link: "current",
  last_reminder: null,
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
  needs_report: false,
  source: "paper",
  received_at: "2027-01-10T09:00:00+01:00",
  flags: { ej_angivna: 3, ej_angivna_paverkar: true, ...NO_SALES },
};
const show = (
  canEdit: boolean,
  rows = [base, sent],
  filter: StatusFilter = "alla",
) =>
  render(
    <StatusTable
      view={view(rows)}
      year={2026}
      genebankId={1}
      filter={filter}
      canEdit={canEdit}
      env="demo"
    />,
  );

describe("StatusTable", () => {
  it("uses singular wording for one omission", () => {
    show(true, [{ ...sent, flags: { ...sent.flags, ej_angivna: 1 } }]);
    expect(screen.getByText("1 ej angiven (påverkar stödet)")).toBeTruthy();
  });
  it("links to Ej svarat with its count and explains an empty list", () => {
    const { unmount } = show(true);
    const tab = screen.getByRole("link", { name: /Ej svarat/ });
    expect(tab.getAttribute("href")).toBe(
      "/stamboken/arsrapport/status/2026?genebank_id=1&filter=ej_svarat",
    );
    expect(within(tab).getByText("1")).toBeTruthy();
    unmount();
    show(true, [sent], "ej_svarat");
    expect(screen.getByText("Alla besättningar har svarat.")).toBeTruthy();
  });
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
  it("uses the link state for mail actions when the invitation has no label", () => {
    show(true, [
      { ...base, inbjudan: null },
      { ...base, herd: "G9002", inbjudan: null, report_link: null },
    ]);
    const invited = within(screen.getByText("G9001").closest("tr")!);
    const waiting = within(screen.getByText("G9002").closest("tr")!);
    for (const name of ["Ny länk", "Skicka påminnelse"]) {
      expect(waiting.queryByRole("button", { name })).toBeNull();
      expect(invited.getByRole("button", { name })).toBeTruthy();
    }
  });
  it("offers only a replacement for a revoked link", () => {
    show(true, [{ ...base, inbjudan: null, report_link: "revoked" }]);
    expect(screen.getByRole("button", { name: "Ny länk" })).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Skicka påminnelse" }),
    ).toBeNull();
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
    expect(
      within(tr).queryByRole("button", { name: "Skicka påminnelse" }),
    ).toBeNull();
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
      expect(undoAccountLink).toHaveBeenCalledWith("G9002", 2026, 41, "demo"),
    );
  });
  it("offers Ny länk only to a manager", () => {
    show(false);
    expect(screen.queryByText("Ny länk")).toBeNull();
  });

  it("queues a reminder without claiming delivery", async () => {
    sendReminder.mockResolvedValue({ ok: true, data: { queued: true } });
    show(true);
    const tr = screen.getByText("G9001").closest("tr")!;
    fireEvent.click(
      within(tr).getByRole("button", { name: "Skicka påminnelse" }),
    );
    expect(sendReminder).toHaveBeenCalledWith("G9001", 2026, "demo");
    expect((await screen.findByRole("status")).textContent).toBe(
      "Påminnelsen ligger i mejlkön.",
    );
    expect(within(tr).queryByText(/skickad/i)).toBeNull();
    expect(refresh).toHaveBeenCalled();
  });
  it("explains when a reminder is already queued or went today", async () => {
    sendReminder.mockResolvedValue({ ok: true, data: { queued: false } });
    show(true);
    fireEvent.click(screen.getByRole("button", { name: "Skicka påminnelse" }));
    expect((await screen.findByRole("status")).textContent).toBe(
      "En påminnelse finns redan i mejlkön eller har skickats i dag.",
    );
    expect(refresh).toHaveBeenCalled();
  });
  it("hides reminder action from helpers", () => {
    show(false);
    expect(
      screen.queryByRole("button", { name: "Skicka påminnelse" }),
    ).toBeNull();
  });
  it("clears the previous queue message when a reminder is refused", async () => {
    sendReminder
      .mockResolvedValueOnce({ ok: true, data: { queued: true } })
      .mockResolvedValueOnce({
        ok: false,
        problem: { status: 409, title: "Rundan är stängd." },
      });
    show(true);
    const button = screen.getByRole("button", { name: "Skicka påminnelse" });
    fireEvent.click(button);
    await screen.findByRole("status");
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
    fireEvent.click(button);
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Rundan är stängd.",
    );
    expect(screen.queryByRole("status")).toBeNull();
    expect(refresh).toHaveBeenCalledTimes(1);
  });
  it("hides the reminder action on a row that needs no report", () => {
    show(true, [sent]);
    expect(
      screen.queryByRole("button", { name: "Skicka påminnelse" }),
    ).toBeNull();
  });
  it.each([
    ["queued", null, "Påminnelse i mejlkön"],
    ["sending", null, "Påminnelse i mejlkön"],
    ["sent", "2027-01-10T09:00:00+01:00", "Påminnelse skickad 10 januari 2027"],
    ["failed", null, "Påminnelsen misslyckades"],
    ["bounced", null, "Påminnelsen studsade"],
    ["sent", null, null],
    ["logged", null, null],
    ["blocked", null, null],
    [null, null, null],
  ] as const)(
    "shows the latest reminder for %s with sent_at %s",
    (status, sent_at, text) => {
      const last_reminder = status
        ? { queued_at: "2027-01-09T10:00:00+01:00", sent_at, status }
        : null;
      show(false, [{ ...base, last_reminder }]);
      const tr = screen.getByText("G9001").closest("tr")!;
      expect(within(tr).queryByText(/påminnelse/i)?.textContent ?? null).toBe(
        text,
      );
    },
  );

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
