import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";

const refresh = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ refresh }) }));

import {
  ReportForm,
  type ReportActions,
  forgetTabWrites,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/ReportForm";
import {
  PENDING_SALE_TEXT,
  type Receipt,
  type ReportCase,
  type ReportView,
  type Submission,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";
import { rabbit, view } from "./fixtures";
import "@/i18n"; // BuyerFields' labels

const receipt: Receipt = {
  submission_id: 1,
  report_id: 1,
  created_at: "2027-01-03T13:32:00+00:00",
  source: "login",
  summary: { kvar: 2, doda: 0, salda: 0, ej_angivna: 0 },
  matrikel: [],
  warnings: [],
};

const ok = <T,>(data: T) => Promise.resolve({ ok: true as const, data });
const fail = (
  status: number,
  extensions: Record<string, unknown> = {},
  detail = "x",
) =>
  Promise.resolve({
    ok: false as const,
    problem: { status, title: "t", detail, extensions },
  });

const actions = (): {
  [K in keyof ReportActions]: ReturnType<typeof vi.fn>;
} & ReportActions =>
  ({
    saveDraft: vi.fn(() =>
      ok({ updated_at: "2026-12-31T10:00:00+00:00", submission_key: null }),
    ),
    dryRun: vi.fn(() => ok({ ok: true, refusals: [], warnings: [] })),
    submitReport: vi.fn(() => ok(receipt)),
    withdrawReport: vi.fn(),
    reportPurchase: vi.fn(),
    sendPurchasePhotos: vi.fn(),
    // the genebank's herds, as GET /v2/genebank/<id>/herds lists them
    getGenebankHerds: vi.fn(() =>
      Promise.resolve({
        success: true as const,
        herds: [
          { herd: "G9001", herd_name: "Gårdsnamn", is_active: true },
          { herd: "G9002", herd_name: "Pappersbesättning", is_active: true },
          { herd: "G9003", herd_name: "Nedlagd", is_active: false },
          { herd: "GX1", herd_name: null, is_active: true },
        ],
      }),
    ),
  }) as never;

beforeEach(() => {
  forgetTabWrites(); // module memory of the tab, as after a hard load
  window.scrollTo = vi.fn(); // jsdom does not implement it
  window.localStorage.clear();
  refresh.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const local = () => {
  const key = Object.keys(window.localStorage).find((k) =>
    k.startsWith("arsrapport:"),
  );
  return key ? window.localStorage.getItem(key) : null;
};
const submittedReport = () => ({
  id: 1,
  status: "submitted",
  source: "login",
  revision: 0,
  received_at: "2027-01-03T13:32:00+00:00",
  report_date: "2027-01-03",
  on_time: true,
  submitted: { rabbits: { "1": { val: "kvar", vikt: 2.8 } } as never },
  can_change: true,
  can_withdraw: true,
  withdraw_until: "2027-01-10T13:32:00+00:00",
  villkor: { hane: true, hona: true, kull: false, i_tid: true },
});
const row = (n: number) =>
  // nosemgrep: javascript.lang.security.audit.detect-non-literal-regexp.detect-non-literal-regexp -- n is a test constant, not user input
  screen.getByRole("group", { name: new RegExp(`G9001-${n}\\b`) });
const choose = (n: number, label: string) =>
  fireEvent.click(within(row(n)).getByLabelText(label));
const fillAll = () => {
  for (const n of [1, 2]) {
    choose(n, "Finns kvar");
    fireEvent.change(within(row(n)).getByLabelText("Vikt"), {
      target: { value: "2,8" },
    });
  }
};
const send = () =>
  fireEvent.click(screen.getByRole("button", { name: "Skicka årsrapporten" }));

describe("ReportForm", () => {
  it("renders the heading with no sticky offset and no dashboard shell", () => {
    render(
      <ReportForm env="demo" view={view()} actions={actions()} stickyTop={0} />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "Årsrapport 2026" }),
    ).toBeTruthy();
    expect(screen.getByText("Besättning G9001 · Gårdsnamn")).toBeTruthy();
    expect(
      screen.getByText(
        "Rapporten gäller kaninerna som fanns i din besättning den 31 december 2026.",
      ),
    ).toBeTruthy();
  });

  it("shows the search, labelled, only from 15 rabbits", () => {
    const { unmount } = render(
      <ReportForm env="demo" view={view()} actions={actions()} />,
    );
    expect(screen.queryByLabelText("Hitta en kanin")).toBeNull();
    expect(screen.getByText("0 av 2 klara")).toBeTruthy(); // counter and filters stay
    unmount();
    const many = Array.from({ length: 15 }, (_, i) => rabbit(i + 1));
    render(
      <ReportForm
        env="demo"
        view={view({ rabbits: many })}
        actions={actions()}
      />,
    );
    expect(screen.getByLabelText("Hitta en kanin")).toBeTruthy();
  });

  it("filters the rabbits bought this year and sends a purchase notice (4a Task 5)", async () => {
    const v = view({
      rabbits: [
        rabbit(1),
        rabbit(2, { kopt: { datum: "2026-05-14", fran: "G9002" } }),
      ],
    });
    const a = actions();
    a.reportPurchase.mockReturnValue(
      ok({
        id: 7,
        number: "G9002-79",
        from_herd: "GX1",
        date: "2026-07-01",
        state: "ny",
      }),
    );
    render(<ReportForm env="demo" view={v} actions={a} />);
    fireEvent.click(screen.getByRole("button", { name: "Köpta" }));
    expect(screen.queryByRole("group", { name: /G9001-1\b/ })).toBeNull();
    expect(within(row(2)).getByText("Köpt 14 maj")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Anmäl köpet" }));
    fireEvent.change(screen.getByLabelText("Kaninens nummer"), {
      target: { value: "G9002-79" },
    });
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    fireEvent.change(screen.getByLabelText("Datum för köpet"), {
      target: { value: "2026-07-01" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Skicka anmälan" }));
    await screen.findByRole("status");
    expect(a.reportPurchase).toHaveBeenCalledWith(
      "G9001",
      2026,
      { number: "G9002-79", from_herd: "utanfor", date: "2026-07-01" },
      "demo",
    );
    expect(refresh).toHaveBeenCalled();
  });

  it("lists a sale given without its day under Sålda by its month (5.3)", () => {
    const sale = { individual_id: 2, number: "G9001-2", to_herd: "G9002" };
    render(
      <ReportForm
        env="demo"
        view={view({
          sales: [
            { ...sale, date: "2026-05-31", day_known: false },
            { ...sale, individual_id: 3, date: "2026-06-14", day_known: true },
          ],
        })}
        actions={actions()}
      />,
    );
    const items = screen.getAllByRole("listitem").map((li) => li.textContent);
    expect(items).toContain("G9001-2 till G9002, maj 2026");
    expect(items).toContain("G9001-2 till G9002, 14 juni 2026");
  });

  it("lists the herd's cases with the queue in plain words (S8)", () => {
    const arenden: ReportCase[] = [
      {
        id: 9,
        what: "kop_saknas",
        number: "G9002-2511",
        photos: 2,
        state: "tolkas",
      },
      {
        id: 8,
        what: "kopanmalan",
        number: "G9002-77",
        photos: 0,
        state: "vantar",
      },
      {
        id: 7,
        what: "forsaljning",
        number: "G9001-1",
        photos: 0,
        state: "arbetar",
      },
      { id: 6, what: "foto", number: "G9001-3", photos: 1, state: "vantar" },
      {
        id: 4,
        what: "kop_saknas",
        number: "G9002-2512",
        photos: 1,
        state: "registrerad",
      },
      { id: 5, what: "inskick", number: null, photos: 1, state: "klart" },
    ];
    const { unmount } = render(
      <ReportForm env="demo" view={view({ arenden })} actions={actions()} />,
    );
    const card = screen
      .getByRole("heading", {
        name: "Ärenden hos genbanksansvarig",
      })
      .closest("section")!;
    expect(
      within(card as HTMLElement)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "Ärende 9 · Köpt kanin finns inte i registret: G9002-2511 · Väntar på att fotot läses",
      "Ärende 8 · Anmält köp: G9002-77 · Väntar på genbanksansvarig",
      "Ärende 7 · Försäljning av G9001-1 · Genbanksansvarig arbetar med det",
      "Ärende 6 · Foto av intyget: G9001-3 · Väntar på genbanksansvarig",
      "Ärende 4 · Köpt kanin finns inte i registret: G9002-2512 · Registrerad, genbanksansvarig avslutar ärendet",
      "Ärende 5 · Inskick med 1 foto · Klart",
    ]);
    unmount();
    // nothing with the queue: no section
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    expect(
      screen.queryByRole("heading", { name: "Ärenden hos genbanksansvarig" }),
    ).toBeNull();
  });

  it("offers only active herds of the genebank but the seller's own and GX1, and sends the herd code", async () => {
    vi.useFakeTimers();
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    choose(1, "Såld");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10);
    });
    const box = screen.getByRole("combobox", { name: "Köparens besättning" });
    fireEvent.mouseDown(box);
    expect(screen.getByText("G9002 – Pappersbesättning")).toBeTruthy();
    expect(screen.queryByText(/G9003/)).toBeNull(); // not active
    expect(screen.queryByText(/G9001 –/)).toBeNull(); // the seller's own
    expect(screen.queryByText(/GX1/)).toBeNull(); // its own choice
    fireEvent.click(screen.getByText("G9002 – Pappersbesättning"));
    fireEvent.change(screen.getByLabelText("Månad"), {
      target: { value: "6" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Spara försäljningen" }),
    );
    expect(within(row(1)).getByText(/Såld till G9002, juni 2026/)).toBeTruthy();
  });

  it("brings the weight back when Ej vägd is turned off again", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    choose(1, "Finns kvar");
    const vikt = () =>
      within(row(1)).getByLabelText("Vikt") as HTMLInputElement;
    fireEvent.change(vikt(), { target: { value: "3,3" } });
    const ejVagd = within(row(1)).getByRole("button", { name: "Ej vägd" });
    fireEvent.click(ejVagd);
    expect(vikt().value).toBe("");
    fireEvent.click(ejVagd);
    expect(vikt().value).toBe("3,3");
  });

  it("does not autosave over Skicka: the timer is cancelled and a late answer is dropped", async () => {
    vi.useFakeTimers();
    const a = actions();
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    fireEvent.change(within(row(1)).getByLabelText("Vikt"), {
      target: { value: "3" },
    });
    choose(2, "Finns kvar");
    fireEvent.change(within(row(2)).getByLabelText("Vikt"), {
      target: { value: "3" },
    });
    send(); // at once, before the 2 s autosave
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(a.submitReport).toHaveBeenCalledTimes(1);
    expect(a.saveDraft).not.toHaveBeenCalled();
  });

  it("saves the held-back changes when Skicka is refused", async () => {
    vi.useFakeTimers();
    const a = actions();
    a.dryRun = vi.fn(() =>
      ok({
        ok: false,
        refusals: [{ code: "x", message: "Nej", individual_id: 1 }],
        warnings: [],
      }),
    ) as unknown as typeof a.dryRun;
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    fireEvent.change(within(row(1)).getByLabelText("Vikt"), {
      target: { value: "3" },
    });
    choose(2, "Finns kvar");
    fireEvent.change(within(row(2)).getByLabelText("Vikt"), {
      target: { value: "3" },
    });
    send(); // before the 2 s autosave; the dry run refuses
    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(a.dryRun).toHaveBeenCalledTimes(1);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2500);
    });
    expect(a.submitReport).not.toHaveBeenCalled();
    expect(a.saveDraft).toHaveBeenCalled();
  });

  it("asks no consent question and links Dina uppgifter to the profile", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    expect(screen.queryByText(/Koharen\? Listan/)).toBeNull();
    expect(screen.getByText("Dina uppgifter")).toBeTruthy();
    expect(
      screen
        .getByRole("link", { name: "Gå till profilen" })
        .getAttribute("href"),
    ).toBe("/stamboken/profil");
  });

  it("counts done rabbits and keeps a row that became done under 'Inte klara'", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    expect(screen.getByText("0 av 2 klara")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Inte klara \(2\)/ }));
    choose(1, "Finns kvar");
    fireEvent.change(within(row(1)).getByLabelText("Vikt"), {
      target: { value: "3" },
    });
    expect(screen.getByText("1 av 2 klara")).toBeTruthy();
    expect(row(1)).toBeTruthy(); // the snapshot keeps it, with its ✓ Klar
    expect(within(row(1)).getByText("✓ Klar")).toBeTruthy();
    expect(
      screen.getByRole("button", { name: /Inte klara \(1\)/ }),
    ).toBeTruthy();
  });

  it("moves from one weight field to the next one that lacks a weight", () => {
    render(
      <ReportForm
        env="demo"
        view={view({ rabbits: [rabbit(1), rabbit(2), rabbit(3)] })}
        actions={actions()}
      />,
    );
    for (const n of [1, 2, 3]) choose(n, "Finns kvar");
    fireEvent.change(within(row(2)).getByLabelText("Vikt"), {
      target: { value: "3" },
    });
    fireEvent.keyDown(within(row(1)).getByLabelText("Vikt"), { key: "Enter" });
    expect(document.activeElement).toBe(within(row(3)).getByLabelText("Vikt"));
  });

  it("restores the choice when the sale dialog is closed unsaved", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    choose(1, "Finns kvar");
    choose(1, "Såld");
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    expect(
      (within(row(1)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (within(row(1)).getByLabelText("Såld") as HTMLInputElement).checked,
    ).toBe(false);
  });

  it("does not count a sale outside the genebank only in the draft as klar: its buyer is gone", () => {
    const draft = {
      data: {
        rabbits: {
          "1": {
            val: "sald",
            sald: { till: "utanfor", ar: 2026, manad: 6, dag: null },
          },
        },
      },
      updated_at: "2026-12-31T11:00:00+00:00",
      submission_key: null,
      own: true,
    } as unknown as ReportView["draft"];
    render(
      <ReportForm env="demo" view={view({ draft })} actions={actions()} />,
    );
    expect(within(row(1)).queryByText("✓ Klar")).toBeNull();
    fireEvent.click(within(row(1)).getByRole("button", { name: "Ändra" }));
    fireEvent.click(screen.getByRole("radio", { name: "Ja" })); // the buyer has e-mail (before 2027)
    fireEvent.change(screen.getByLabelText(/Köparens namn/), {
      target: { value: "Ola Köpare" },
    });
    fireEvent.change(screen.getByLabelText(/^Ort/), {
      target: { value: "Visby" },
    });
    fireEvent.change(screen.getByLabelText(/^Postadress/), {
      target: { value: "Testgatan 1" },
    });
    fireEvent.change(screen.getByLabelText(/^E-post/), {
      target: { value: "ola@example.invalid" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Spara försäljningen" }),
    );
    expect(within(row(1)).getByText("✓ Klar")).toBeTruthy();
  });

  it("lets go of a kept buyer once the row is no longer a sale outside the genebank (FB6)", () => {
    const kept = {
      data: {
        rabbits: {
          "1": {
            val: "sald",
            sald: {
              till: "utanfor",
              ar: 2026,
              manad: 6,
              dag: 1,
              kopare_id: 7,
            },
          },
        },
      },
      updated_at: "2026-12-31T11:00:00+00:00",
      submission_key: null,
      own: true,
    } as unknown as ReportView["draft"];
    render(
      <ReportForm
        env="demo"
        view={view({
          draft: kept,
          rabbits: [rabbit(1, { kept_buyer_date: "2026-06-01" })],
        })}
        actions={actions()}
      />,
    );
    fireEvent.click(within(row(1)).getByRole("button", { name: "Ändra" }));
    expect(screen.getByText(/Köparen finns sparad/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    choose(1, "Finns kvar");
    choose(1, "Såld");
    expect(screen.queryByText(/Köparen finns sparad/)).toBeNull();
  });

  // Jonas 2026-11-26: before the first Skicka the dialog registers the sale at once, after Sälj's tick box.
  const ACK =
    "Jag har tagit del av informationen och vill ta bort kaninen från min besättning.";
  const sellingActions = () => ({
    ...actions(),
    sellNow: vi.fn<(...args: unknown[]) => Promise<unknown>>(() =>
      ok({ operation_id: "op" }),
    ),
    undoSale: vi.fn<(...args: unknown[]) => Promise<unknown>>(() => ok(null)),
  });
  const typeSaleOutside = () => {
    choose(1, "Såld");
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    fireEvent.click(screen.getByRole("radio", { name: "Ja" })); // e-mail, before 2027
    for (const [label, value] of [
      [/Köparens namn/, "Ola Köpare"],
      [/^Ort/, "Visby"],
      [/^Postadress/, "Testgatan 1"],
      [/^E-post/, "ola@example.invalid"],
    ] as const)
      fireEvent.change(screen.getByLabelText(label), { target: { value } });
    fireEvent.change(screen.getByLabelText("Månad"), {
      target: { value: "6" },
    });
  };
  const spara = () =>
    fireEvent.click(
      screen.getByRole("button", { name: "Spara försäljningen" }),
    );

  it("registers a sale at once once the box is ticked, then lets go of the row and reads the view again", async () => {
    vi.useFakeTimers();
    const a = sellingActions();
    render(<ReportForm env="demo" view={view()} actions={a as never} />);
    choose(1, "Finns kvar"); // an entry the sale must take away
    typeSaleOutside();
    expect(
      screen.getByText(
        "Köparen får ett mejl om vad föreningen sparar. Du kan ångra försäljningen i 7 dagar.",
      ),
    ).toBeTruthy();
    spara();
    expect(
      screen.getByText("Kryssa i rutan för att registrera försäljningen."),
    ).toBeTruthy();
    expect(a.sellNow).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText(ACK));
    await act(async () => {
      spara();
      await vi.advanceTimersByTimeAsync(10);
    });
    expect(a.sellNow).toHaveBeenCalledTimes(1);
    const [herdCode, year, id, sald] = a.sellNow.mock.calls[0] as unknown as [
      string,
      number,
      number,
      { till: string; manad: number; kopare: { name: string } },
    ];
    expect([
      herdCode,
      year,
      id,
      sald.till,
      sald.manad,
      sald.kopare.name,
    ]).toEqual(["G9001", 2026, 1, "utanfor", 6, "Ola Köpare"]);
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(refresh).toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    const data = a.saveDraft.mock.calls.at(-1)?.[2];
    expect(data?.rabbits["1"]).toBeUndefined(); // the register holds the sale now, not the draft
  });

  it("leaves a late sale to Skicka, which asks for the reason", () => {
    const a = sellingActions();
    const round = {
      start_date: "2025-12-31",
      deadline: "2026-01-31",
      end_date: "2026-03-01",
      activated: true,
      open: false,
    };
    render(
      <ReportForm
        env="demo"
        view={view({ access: "manager", round })}
        actions={a as never}
      />,
    );
    typeSaleOutside();
    expect(screen.queryByLabelText(ACK)).toBeNull();
    spara();
    expect(a.sellNow).not.toHaveBeenCalled();
  });

  it("counts the year's sales the report did not write among Sålda", () => {
    const report = {
      ...submittedReport(),
      submitted: {
        rabbits: { "1": { val: "kvar", vikt: 2.8 } },
        salda_direkt: [{ individual_id: 3 }, { individual_id: 4 }],
      } as never,
    };
    render(
      <ReportForm env="demo" view={view({ report })} actions={actions()} />,
    );
    expect(screen.getByText("Sålda").previousElementSibling?.textContent).toBe(
      "2",
    );
  });

  it("keeps the dialog open with the server's refusal", async () => {
    const a = sellingActions();
    a.sellNow.mockImplementationOnce(() =>
      fail(422, {
        refusals: [
          {
            individual_id: 1,
            code: "kopare",
            message: "Ange köparens postadress.",
          },
        ],
      }),
    );
    render(<ReportForm env="demo" view={view()} actions={a as never} />);
    typeSaleOutside();
    fireEvent.click(screen.getByLabelText(ACK));
    await act(async () => spara());
    expect(
      within(screen.getByRole("dialog")).getByText("Ange köparens postadress."),
    ).toBeTruthy();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("offers Ångra on a sale of the year and on a rabbit counted by its move, and asks first", async () => {
    const a = sellingActions();
    const sales = [
      {
        individual_id: 3,
        number: "G9001-3",
        to_herd: "GX1",
        date: "2026-06-30",
        day_known: true,
        undo: 55,
      },
    ];
    const moved = rabbit(2, {
      state: "via_flytt",
      later: { kind: "TRANSFER", date: "2027-01-05" },
      undo: 56,
      undo_to: "G9002",
    });
    render(
      <ReportForm
        env="demo"
        view={view({ sales, rabbits: [rabbit(1), moved] })}
        actions={a as never}
      />,
    );
    const BACK = "Kaninen kommer tillbaka till din besättning.";
    const NOTE =
      "Kaninen kommer tillbaka till din besättning, och köparens uppgifter tas bort.";
    for (const [i, id, note] of [
      [0, 56, BACK], // the row comes before "Sålda under 2026"; sold to G9002, a herd in the genebank
      [1, 55, NOTE], // sold outside the genebank
    ] as const) {
      fireEvent.click(screen.getAllByRole("button", { name: "Ångra" })[i]);
      const dialog = screen.getByRole("dialog");
      expect(within(dialog).getByText(note)).toBeTruthy();
      expect(a.undoSale).toHaveBeenCalledTimes(i); // nothing undone before the question is answered
      await act(async () =>
        fireEvent.click(
          within(dialog).getByRole("button", { name: "Ångra försäljning" }),
        ),
      );
      expect(a.undoSale.mock.calls[i].slice(0, 3)).toEqual(["G9001", 2026, id]);
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    }
    expect(refresh).toHaveBeenCalled();
  });

  it("holds a buyer outside the genebank in memory only: the draft and localStorage never get it", async () => {
    vi.useFakeTimers();
    const a = actions();
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Såld");
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    fireEvent.click(screen.getByRole("radio", { name: "Ja" })); // the buyer has e-mail (before 2027)
    fireEvent.change(screen.getByLabelText(/Köparens namn/), {
      target: { value: "Ola Köpare" },
    });
    fireEvent.change(screen.getByLabelText(/^Ort/), {
      target: { value: "Visby" },
    });
    fireEvent.change(screen.getByLabelText(/^Postadress/), {
      target: { value: "Testgatan 1" },
    });
    fireEvent.change(screen.getByLabelText(/^E-post/), {
      target: { value: "ola@example.invalid" },
    });
    fireEvent.change(screen.getByLabelText("Månad"), {
      target: { value: "6" },
    });
    fireEvent.click(
      screen.getByRole("button", { name: "Spara försäljningen" }),
    );
    expect(
      within(row(1)).getByText(/Såld till utanför genbanken, juni 2026/),
    ).toBeTruthy();
    expect(local()).not.toMatch(/Ola|kopare/);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(1);
    const [, , data] = a.saveDraft.mock.calls[0];
    expect(JSON.stringify(data)).not.toMatch(/Ola|Visby|kopare/);
    expect(data.rabbits["1"].sald.till).toBe("utanfor");
    expect(local()).toBeNull(); // the server confirmed
  });

  it("shows 'Markera resten' on a long list only once the last row has been seen", () => {
    let fire: (e: { isIntersecting: boolean }[]) => void = () => {};
    vi.stubGlobal(
      "IntersectionObserver",
      class {
        constructor(cb: typeof fire) {
          fire = cb;
        }
        observe() {}
        disconnect() {}
      },
    );
    const many = Array.from({ length: 31 }, (_, i) => rabbit(i + 1));
    render(
      <ReportForm
        env="demo"
        view={view({ rabbits: many })}
        actions={actions()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "Markera resten som finns kvar" }),
    ).toBeNull();
    act(() => fire([{ isIntersecting: true }]));
    fireEvent.click(
      screen.getByRole("button", { name: "Markera resten som finns kvar" }),
    );
    expect(
      screen.getByText(
        /Markera 31 kaniner som finns kvar\? Vuxna kaniner behöver ändå vikt eller Ej vägd\./,
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ja, markera" }));
    expect(screen.getByText("0 av 31 klara")).toBeTruthy(); // adults still need a weight
    expect(
      (within(row(5)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(true);
  });

  it("puts every refusal in a focused error box with a link per rabbit and one to Hälsa", async () => {
    const a = actions();
    a.dryRun.mockImplementation(() =>
      ok({
        ok: false,
        refusals: [
          { individual_id: 2, code: "vikt_saknas", message: "x" },
          { individual_id: null, code: "halsa_saknas", message: "x" },
        ],
        warnings: [],
      }),
    );
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    fireEvent.change(within(row(1)).getByLabelText("Vikt"), {
      target: { value: "3" },
    });
    send();
    const heading = await screen.findByText("1 kanin är inte klara");
    const errorBox = heading.closest("div")!;
    await waitFor(() => expect(document.activeElement).toBe(errorBox));
    expect(
      within(errorBox).getByRole("link", { name: /G9001-2/ }),
    ).toBeTruthy();
    expect(
      within(errorBox).getByRole("link", {
        name: "Välj Inga sjukdomsfall eller defekter, eller Ja.",
      }),
    ).toBeTruthy();
    expect(a.submitReport).not.toHaveBeenCalled();
    fireEvent.click(
      within(errorBox).getByRole("button", {
        name: "Visa bara dem som inte är klara",
      }),
    );
    expect(screen.getAllByRole("group", { name: /G9001-/ })).toHaveLength(1);
  });

  it("shows the save note once, next to Skicka", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    expect(screen.getAllByText(/^Inte inskickad\. /)).toHaveLength(1);
  });

  it("names the rabbit in a receipt warning", async () => {
    const a = actions();
    a.submitReport.mockImplementationOnce(() =>
      ok({
        ...receipt,
        warnings: [
          {
            individual_id: 1,
            code: "vikt_ovanlig",
            message: "Stämmer 7,2 kg?",
          },
        ],
      }),
    );
    render(<ReportForm env="demo" view={view()} actions={a} />);
    fillAll();
    send();
    expect(
      await screen.findByText(/G9001-1 Kanin1: Stämmer 7,2 kg\?/),
    ).toBeTruthy();
  });

  it("retries a timed-out Skicka with the same key and body, without a new dry run, and then shows the receipt", async () => {
    const a = actions();
    a.submitReport
      .mockImplementationOnce(() => fail(408)) // the server committed; the answer was lost
      .mockImplementationOnce(() => ok(receipt));
    render(<ReportForm env="demo" view={view()} actions={a} />);
    fillAll();
    send();
    expect(
      await screen.findAllByText(
        "Vi vet inte om rapporten kom fram. Tryck Försök igen. Den skickas inte två gånger.",
      ),
    ).not.toHaveLength(0);
    // the form is read-only until the answer comes
    expect(
      (within(row(1)).getByLabelText("Vikt") as HTMLInputElement).closest(
        "fieldset[disabled]",
      ),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    const headline = await screen.findByText(
      /Klart\. Årsrapporten för G9001 kom in/,
    );
    expect(document.activeElement).toBe(headline); // a screen reader hears it
    expect(a.dryRun).toHaveBeenCalledTimes(1);
    expect(a.submitReport).toHaveBeenCalledTimes(2);
    const [first, second] = a.submitReport.mock.calls.map(
      (c) => c[2] as Submission,
    );
    expect(second).toEqual(first);
    expect(first.submission_key).toMatch(/^[0-9a-f-]{36}$/);
    expect(refresh).toHaveBeenCalled();
  });

  it("autosaves 2 s after the last change, and loads the server's draft on a 409", async () => {
    vi.useFakeTimers();
    const a = actions();
    a.saveDraft.mockImplementationOnce(() =>
      fail(409, {
        draft: {
          data: { rabbits: { "2": { val: "kvar", vikt: 3 } } },
          updated_at: "2026-12-31T11:00:00+00:00",
          submission_key: null,
          own: false,
        },
      }),
    );
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1900);
    });
    expect(a.saveDraft).not.toHaveBeenCalled();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(200);
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(1);
    expect(
      screen.getAllByText(
        "Rapporten har ändrats på en annan enhet. Vi har läst in den senaste.",
      ),
    ).not.toHaveLength(0);
    expect(
      (within(row(2)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (within(row(1)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(false);
  });

  it("shows the receipt for a submitted report, with Ändra and Dra tillbaka", () => {
    const v = view({
      report: {
        id: 1,
        status: "submitted",
        source: "login",
        revision: 0,
        received_at: "2027-01-03T13:32:00+00:00",
        report_date: "2027-01-03",
        on_time: true,
        submitted: {
          rabbits: {
            "1": { val: "kvar", vikt: 2.8 },
            "2": {
              val: "dod",
              dod: {
                ar: 2026,
                manad: 3,
                dag: null,
                slaktad: false,
                anteckning: null,
              },
            },
          } as never,
        },
        can_change: true,
        can_withdraw: true,
        withdraw_until: "2027-01-10T13:32:00+00:00",
        villkor: { hane: true, hona: true, kull: false, i_tid: true },
      },
    });
    render(<ReportForm env="demo" view={v} actions={actions()} />);
    expect(
      screen.getByText(
        /Klart\. Årsrapporten för G9001 kom in 3 januari 2027 kl\. 14\.32\./,
      ),
    ).toBeTruthy();
    expect(screen.getByText("✗ Kull")).toBeTruthy();
    expect(screen.getByRole("status", { name: "" }).textContent).toBe(
      "Inskickad",
    ); // the time is in the heading only
    expect(screen.getByRole("button", { name: "Dra tillbaka" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Ändra" }));
    expect(
      (within(row(1)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      screen.getByRole("button", { name: "Skicka ändringarna" }),
    ).toBeTruthy();
  });

  it("takes empty buyer fields on Ändra for the sale outside the report holds", () => {
    const sale = { till: "utanfor", ar: 2026, manad: 6, dag: null };
    const report = {
      ...submittedReport(),
      submitted: { rabbits: { "1": { val: "sald", sald: sale } } as never },
    };
    render(
      <ReportForm env="demo" view={view({ report })} actions={actions()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra" }));
    fireEvent.click(within(row(1)).getByRole("button", { name: "Ändra" }));
    expect(
      screen.getByText(/Lämna fälten tomma om köparen är rätt/),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Spara försäljningen" }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers Dra tillbaka to a caretaker with a sale, and says a pending sale waits", () => {
    // FB5: the withdrawal leaves the owner's sale standing, so it is offered
    const sale = {
      "1": {
        val: "sald",
        sald: { till: "G9002", ar: 2026, manad: 3, dag: null },
      },
    } as never;
    render(
      <ReportForm
        env="demo"
        view={view({
          access: "caretaker",
          can_sell: false,
          forslag: [
            {
              individual_id: 1,
              to_herd: "G9002",
              sale_date: "2026-03-31",
              state: "foreslagen",
            },
          ],
          report: {
            id: 1,
            status: "submitted",
            source: "login",
            revision: 0,
            received_at: "2027-01-03T13:32:00+00:00",
            report_date: "2027-01-03",
            on_time: true,
            submitted: { rabbits: sale },
            can_change: true,
            can_withdraw: true,
            withdraw_until: "2027-01-10T13:32:00+00:00",
            villkor: { hane: true, hona: true, kull: true, i_tid: true },
          },
        })}
        actions={actions()}
      />,
    );
    expect(screen.getByRole("button", { name: "Dra tillbaka" })).toBeTruthy();
    expect(screen.getByText(PENDING_SALE_TEXT)).toBeTruthy();
  });

  it("says a sale waits from the receipt until the refresh, then from the view alone", async () => {
    // a retry after a timeout gets the first receipt, though the sale may have been approved meanwhile
    const a = actions();
    a.submitReport.mockImplementation(() =>
      ok({ ...receipt, summary: { ...receipt.summary, salda: 1, vantar: 1 } }),
    );
    const { rerender } = render(
      <ReportForm env="demo" view={view()} actions={a} />,
    );
    fillAll();
    send();
    expect(await screen.findByText(PENDING_SALE_TEXT)).toBeTruthy();
    expect(refresh).toHaveBeenCalled();
    const refreshed = (state: "foreslagen" | "godkand") =>
      view({
        report: submittedReport(),
        forslag: [
          {
            individual_id: 1,
            to_herd: "G9002",
            sale_date: "2026-10-03",
            state,
          },
        ],
      });
    rerender(<ReportForm env="demo" view={refreshed("godkand")} actions={a} />);
    expect(
      screen.getByText(/Klart\. Årsrapporten för G9001 kom in/),
    ).toBeTruthy();
    expect(screen.queryByText(PENDING_SALE_TEXT)).toBeNull();
    rerender(
      <ReportForm env="demo" view={refreshed("foreslagen")} actions={a} />,
    );
    expect(screen.getByText(PENDING_SALE_TEXT)).toBeTruthy();
  });

  it("says the round is closed instead of showing the form", () => {
    render(
      <ReportForm
        env="demo"
        view={view({
          round: {
            start_date: null,
            deadline: null,
            end_date: null,
            activated: true,
            open: false,
          },
        })}
        actions={actions()}
      />,
    );
    expect(
      screen.getByText(
        "Rundan är stängd. Kontakta genbanksansvarig om något behöver ändras.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Skicka årsrapporten" }),
    ).toBeNull();
  });

  it("offers Anmäl köpet only where the server takes it: not to an editor before the round opens", () => {
    const at = (round: Partial<ReportView["round"]>) => {
      cleanup();
      const before = view().round;
      render(
        <ReportForm
          env="demo"
          view={view({ access: "manager", round: { ...before, ...round } })}
          actions={actions()}
        />,
      );
      return !!screen.queryByRole("button", { name: "Anmäl köpet" });
    };
    expect(at({})).toBe(true); // open
    expect(at({ start_date: "2999-12-31", open: false })).toBe(false); // not yet open
    expect(
      at({ start_date: "2025-12-31", end_date: "2026-03-30", open: false }),
    ).toBe(true); // after the end: an editor still writes
  });

  it("says when the round opens instead of that it is closed", () => {
    render(
      <ReportForm
        env="demo"
        view={view({
          round: {
            start_date: "2999-12-31",
            deadline: null,
            end_date: null,
            activated: true,
            open: false,
          },
        })}
        actions={actions()}
      />,
    );
    expect(screen.getByText("Rundan öppnar 31 december 2999.")).toBeTruthy();
  });

  it("serialises autosaves: the second goes out only after the first is answered, with the version it returned", async () => {
    vi.useFakeTimers();
    const a = actions();
    let release: (v: unknown) => void = () => {};
    a.saveDraft
      .mockImplementationOnce(() => new Promise((r) => (release = r)))
      .mockImplementationOnce(() =>
        ok({ updated_at: "2026-12-31T10:00:02+00:00", submission_key: null }),
      );
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    choose(2, "Finns kvar"); // while the first save is in flight
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(1);
    await act(async () => {
      release({
        ok: true,
        data: { updated_at: "2026-12-31T10:00:01+00:00", submission_key: null },
      });
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(2);
    expect(a.saveDraft.mock.calls[1][3]).toBe("2026-12-31T10:00:01+00:00");
    expect(a.saveDraft.mock.calls[1][2].rabbits["2"]).toBeTruthy();
  });

  it("keeps a half-filled death and a disease without a count in the draft", async () => {
    vi.useFakeTimers();
    const a = actions();
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Död"); // no month yet
    fireEvent.click(screen.getByLabelText("Ja, fyll i"));
    fireEvent.change(screen.getByLabelText("Annat, vad"), {
      target: { value: "Förkylning" },
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    const data = a.saveDraft.mock.calls[0][2];
    expect(data.form.rabbits["1"].val).toBe("dod");
    expect(data.form.diseases.annat.namn).toBe("Förkylning");
  });

  it("after a 409 with no draft reloads the view and shows the current receipt", async () => {
    vi.useFakeTimers();
    const a = actions();
    a.saveDraft.mockImplementationOnce(() => fail(409, { draft: null }));
    const { rerender } = render(
      <ReportForm env="demo" view={view()} actions={a} />,
    );
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(refresh).toHaveBeenCalled();
    rerender(
      <ReportForm
        env="demo"
        view={view({ report: submittedReport() })}
        actions={a}
      />,
    );
    expect(
      screen.getByText(/Klart\. Årsrapporten för G9001 kom in/),
    ).toBeTruthy();
  });

  it("treats a rejected server action as an error box on the dry run, and as a timeout on Skicka", async () => {
    const a = actions();
    a.dryRun.mockImplementationOnce(() => Promise.reject(new Error("network")));
    render(<ReportForm env="demo" view={view()} actions={a} />);
    fillAll();
    send();
    expect(
      await screen.findByText("Det gick inte att nå servern. Försök igen."),
    ).toBeTruthy();
    a.submitReport
      .mockImplementationOnce(() => Promise.reject(new Error("network")))
      .mockImplementationOnce(() => ok(receipt));
    send();
    await screen.findAllByText(/Vi vet inte om rapporten kom fram/);
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(
      await screen.findByText(/Klart\. Årsrapporten för G9001 kom in/),
    ).toBeTruthy();
    const [first, second] = a.submitReport.mock.calls.map((c) => c[2]);
    expect(second).toEqual(first);
  });

  it("keeps the local copy apart per data environment and never saves across one", async () => {
    vi.useFakeTimers();
    const a = actions();
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    expect(Object.keys(window.localStorage)).toEqual([
      "arsrapport:demo:G9001:2026",
    ]);
    document.cookie = "sb_mode=prod"; // switched while the demo form is open
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft).not.toHaveBeenCalled();
    cleanup();
    render(<ReportForm env="prod" view={view()} actions={actions()} />);
    expect(
      (within(row(1)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(false);
    document.cookie = "sb_mode=; max-age=0";
  });

  it("keeps the server's newer draft over an older local copy until the user chooses", async () => {
    vi.useFakeTimers(); // Codex 1: autosave never sends the old copy with the new updated_at
    const draft = {
      data: { rabbits: { "2": { val: "kvar", vikt: 3 } } } as never,
      updated_at: "2026-12-31T11:00:00+00:00",
      submission_key: null,
      own: false,
    };
    const copy = (updated_at: string) =>
      window.localStorage.setItem(
        "arsrapport:demo:G9001:2026",
        JSON.stringify({
          data: { rabbits: { "1": { val: "kvar", vikt: 2 } } },
          updated_at,
          revision: null,
        }),
      );
    const kvar = () =>
      [1, 2].map(
        (n) =>
          (within(row(n)).getByLabelText("Finns kvar") as HTMLInputElement)
            .checked,
      );

    copy(draft.updated_at); // edited from the version the server still has
    render(
      <ReportForm env="demo" view={view({ draft })} actions={actions()} />,
    );
    expect(kvar()).toEqual([true, false]);
    cleanup();

    copy("2026-12-31T10:00:00+00:00"); // edited from an older one
    const a = actions();
    render(<ReportForm env="demo" view={view({ draft })} actions={a} />);
    expect(kvar()).toEqual([false, true]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(a.saveDraft).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Använd den lokala kopian" }),
    );
    expect(kvar()).toEqual([true, false]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(1); // the user's choice
    expect(a.saveDraft.mock.calls[0][2].rabbits["1"].val).toBe("kvar");
    expect(a.saveDraft.mock.calls[0][3]).toBe(draft.updated_at);
    cleanup();
    forgetTabWrites(); // a new page load: the mock's answer above is not this view's history

    copy("2026-12-31T10:00:00+00:00");
    render(
      <ReportForm env="demo" view={view({ draft })} actions={actions()} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Behåll den sparade" }));
    expect(local()).toBeNull();
    expect(kvar()).toEqual([false, true]);
  });

  it("stamps the local copy with the version a save returned while a newer edit waits", async () => {
    vi.useFakeTimers();
    const a = actions();
    let release: (v: unknown) => void = () => {};
    a.saveDraft.mockImplementationOnce(() => new Promise((r) => (release = r)));
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    choose(2, "Finns kvar"); // while the first save is in flight
    await act(async () => {
      release({
        ok: true,
        data: { updated_at: "2026-12-31T10:00:01+00:00", submission_key: null },
      });
    });
    const kept = JSON.parse(local()!);
    expect(kept.updated_at).toBe("2026-12-31T10:00:01+00:00");
    expect(kept.data.rabbits["2"].val).toBe("kvar");
  });

  it("gives a draft with no key (from Dra tillbaka) a new submission key", async () => {
    vi.useFakeTimers();
    const a = actions();
    const spent = "11111111-1111-4111-8111-111111111111";
    a.saveDraft.mockImplementationOnce(() =>
      fail(409, {
        draft: {
          data: { rabbits: {} },
          updated_at: "2026-12-31T11:00:00+00:00",
          submission_key: null,
        },
      }),
    );
    render(
      <ReportForm
        env="demo"
        view={view({
          draft: {
            data: { rabbits: {} } as never,
            updated_at: "2026-12-31T10:00:00+00:00",
            submission_key: spent,
            own: true,
          },
        })}
        actions={a}
      />,
    );
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    choose(2, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft.mock.calls[0][4]).toBe(spent);
    expect(a.saveDraft.mock.calls[1][4]).not.toBe(spent);
  });

  it("locks editing and Skicka while a conflict reload is pending, and unlocks when the view arrives", async () => {
    vi.useFakeTimers();
    const a = actions();
    a.saveDraft.mockImplementationOnce(() => fail(409, { draft: null }));
    const { rerender } = render(
      <ReportForm env="demo" view={view()} actions={a} />,
    );
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.getAllByText("Hämtar senaste versionen…")).not.toHaveLength(
      0,
    );
    expect(
      within(row(1)).getByLabelText("Finns kvar").matches(":disabled"),
    ).toBe(true);
    expect(
      (
        screen.getByRole("button", {
          name: "Skicka årsrapporten",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    rerender(<ReportForm env="demo" view={view()} actions={a} />);
    expect(screen.queryByText("Hämtar senaste versionen…")).toBeNull();
    expect(
      within(row(1)).getByLabelText("Finns kvar").matches(":disabled"),
    ).toBe(false);
  });

  it("closes the sale dialog when a reload starts, and after 10 s stays locked with a full-reload button; a late view still syncs", async () => {
    vi.useFakeTimers();
    const a = actions();
    a.saveDraft.mockImplementationOnce(() => fail(409, { draft: null }));
    const { rerender } = render(
      <ReportForm env="demo" view={view()} actions={a} />,
    );
    choose(1, "Finns kvar");
    choose(2, "Såld"); // the dialog opens while the first save is on its way
    expect(screen.getByRole("dialog")).toBeTruthy();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(screen.getByRole("button", { name: "Ladda om sidan" })).toBeTruthy();
    expect(
      within(row(1)).getByLabelText("Finns kvar").matches(":disabled"),
    ).toBe(true);
    rerender(<ReportForm env="demo" view={view()} actions={a} />); // the late answer
    expect(screen.queryByRole("button", { name: "Ladda om sidan" })).toBeNull();
    expect(
      within(row(1)).getByLabelText("Finns kvar").matches(":disabled"),
    ).toBe(false);
    expect(
      (within(row(1)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(false); // reset from the reloaded view
  });

  // Next shows the view object from before the save again when the user comes Back (Jonas 2026-11-26).
  const savedDraft = (rabbits: Record<string, { val: string }>) =>
    view({
      draft: {
        data: { rabbits },
        updated_at: "2026-12-31T10:00:00+00:00",
        submission_key: null,
        own: true,
      },
    } as never);
  const checked = (n: number) =>
    (within(row(n)).getByLabelText("Finns kvar") as HTMLInputElement).checked;
  // saveDraft as the server answers it: a save from an older version gets the 409
  const server = () => {
    let at: string | null = null;
    let stored: unknown = null;
    return vi.fn(
      (_h: string, _y: number, data: unknown, seen: string | null) => {
        if (seen !== at)
          return fail(409, {
            draft: {
              data: stored,
              updated_at: at,
              submission_key: null,
              own: true,
            },
          });
        stored = data;
        at = "2026-12-31T10:00:00+00:00";
        return ok({ updated_at: at, submission_key: null });
      },
    );
  };
  const answerLater = () => {
    let answer!: () => void;
    const call = new Promise((resolve) => {
      answer = () =>
        resolve({
          ok: true,
          data: {
            updated_at: "2026-12-31T10:00:00+00:00",
            submission_key: null,
          },
        });
    });
    return { call, answer };
  };

  it("reads the page again when Back brings a view from before its own save, and saves on without a conflict", async () => {
    vi.useFakeTimers();
    const a = actions();
    a.saveDraft.mockImplementation(server());
    const before = view();
    const first = render(<ReportForm env="demo" view={before} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(1);
    first.unmount(); // to the profile, and Back
    const { rerender } = render(
      <ReportForm env="demo" view={before} actions={a} />,
    );
    await act(async () => {}); // the reload asks for the page once the writes on their way have answered
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(screen.getAllByText("Hämtar senaste versionen…")).not.toHaveLength(
      0,
    );
    expect(
      within(row(2)).getByLabelText("Finns kvar").matches(":disabled"),
    ).toBe(true);
    rerender(
      <ReportForm
        env="demo"
        view={savedDraft({ "1": { val: "kvar" } })}
        actions={a}
      />,
    );
    expect(checked(1)).toBe(true);
    expect(screen.getAllByText(/sparat \(senast 11\.00\)/)).not.toHaveLength(0);
    choose(2, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(2);
    expect(a.saveDraft.mock.calls[1][3]).toBe("2026-12-31T10:00:00+00:00");
    expect(screen.queryByText(/annan enhet/)).toBeNull();
  });

  it("keeps a change made just before leaving, when Back reads the page again", async () => {
    vi.useFakeTimers();
    const a = actions();
    const before = view();
    const first = render(<ReportForm env="demo" view={before} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    choose(2, "Finns kvar"); // left before its autosave: only the local copy has it
    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    first.unmount();
    const { rerender } = render(
      <ReportForm env="demo" view={before} actions={a} />,
    );
    await act(async () => {}); // the reload asks for the page once the writes on their way have answered
    expect(refresh).toHaveBeenCalledTimes(1);
    rerender(
      <ReportForm
        env="demo"
        view={savedDraft({ "1": { val: "kvar" } })}
        actions={a}
      />,
    );
    expect([checked(1), checked(2)]).toEqual([true, true]);
    expect(
      screen.queryByText("Osparade ändringar på den här enheten"),
    ).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(2);
    expect(a.saveDraft.mock.calls[1][2]).toMatchObject({
      rabbits: { "1": { val: "kvar" }, "2": { val: "kvar" } },
    });
  });

  it("waits for a save still on its way when Back comes first, then reads the page again", async () => {
    vi.useFakeTimers();
    const a = actions();
    const later = answerLater();
    a.saveDraft.mockImplementationOnce(() => later.call);
    const before = view();
    const first = render(<ReportForm env="demo" view={before} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(1);
    first.unmount(); // Back before the save has answered
    const { rerender } = render(
      <ReportForm env="demo" view={before} actions={a} />,
    );
    expect(screen.getAllByText("Hämtar senaste versionen…")).not.toHaveLength(
      0,
    );
    expect(refresh).not.toHaveBeenCalled(); // not before the save is in
    await act(async () => {
      later.answer();
    });
    await act(async () => {}); // the reload asks for the page once the writes on their way have answered
    expect(refresh).toHaveBeenCalledTimes(1);
    rerender(
      <ReportForm
        env="demo"
        view={savedDraft({ "1": { val: "kvar" } })}
        actions={a}
      />,
    );
    expect(checked(1)).toBe(true);
  });

  it("reads a view again after a save from another page of the same report", async () => {
    vi.useFakeTimers();
    const a = actions();
    const ordinary = view();
    render(<ReportForm env="demo" view={ordinary} actions={a} />).unmount();
    // the paper page of the same report has its own view and the same draft
    const other = render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    other.unmount();
    render(<ReportForm env="demo" view={ordinary} actions={a} />);
    await act(async () => {}); // the reload asks for the page once the writes on their way have answered
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("shows the reload on the receipt too, with Ladda om sidan when it does not answer", async () => {
    vi.useFakeTimers();
    const a = actions();
    const sent = view({ report: submittedReport() } as never);
    render(<ReportForm env="demo" view={sent} actions={a} />).unmount();
    const other = render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    other.unmount();
    render(<ReportForm env="demo" view={sent} actions={a} />);
    expect(screen.getAllByText("Hämtar senaste versionen…")).not.toHaveLength(
      0,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(screen.getByRole("button", { name: "Ladda om sidan" })).toBeTruthy();
  });

  it("leaves a newer local copy alone when an older save answers", async () => {
    vi.useFakeTimers();
    const a = actions();
    const later = answerLater();
    a.saveDraft.mockImplementationOnce(() => later.call);
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    // a form mounted later (Back, another tab) wrote its own copy meanwhile
    const key = Object.keys(window.localStorage).find((k) =>
      k.startsWith("arsrapport:"),
    )!;
    window.localStorage.setItem(
      key,
      JSON.stringify({
        data: { rabbits: { "2": { val: "kvar" } } },
        updated_at: null,
        revision: null,
        writer: "a form mounted later",
      }),
    );
    await act(async () => {
      later.answer();
    });
    expect(local()).toContain('"2"');
  });

  it("waits for every save the old form still has queued before it reads the page again", async () => {
    vi.useFakeTimers();
    const a = actions();
    const first = answerLater();
    const second = answerLater();
    a.saveDraft
      .mockImplementationOnce(() => first.call)
      .mockImplementationOnce(() => second.call);
    const before = view();
    const old = render(<ReportForm env="demo" view={before} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    choose(2, "Finns kvar"); // its autosave waits behind the first save
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(1);
    old.unmount();
    render(<ReportForm env="demo" view={before} actions={a} />);
    await act(async () => {
      first.answer();
    });
    expect(a.saveDraft).toHaveBeenCalledTimes(2); // the old form sends the queued one
    expect(refresh).not.toHaveBeenCalled();
    await act(async () => {
      second.answer();
    });
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("leaves another form's local copy alone when a late save meets a conflict", async () => {
    vi.useFakeTimers();
    const a = actions();
    let answer!: (v: unknown) => void;
    a.saveDraft.mockImplementationOnce(
      () => new Promise((resolve) => (answer = resolve)),
    );
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    const key = Object.keys(window.localStorage).find((k) =>
      k.startsWith("arsrapport:"),
    )!;
    window.localStorage.setItem(
      key,
      JSON.stringify({
        data: { rabbits: { "2": { val: "kvar" } } },
        updated_at: null,
        revision: null,
        writer: "a form mounted later",
      }),
    );
    await act(async () => {
      answer({
        ok: false,
        problem: {
          status: 409,
          title: "t",
          detail: "x",
          extensions: {
            draft: {
              data: { rabbits: {} },
              updated_at: "2026-12-31T11:00:00+00:00",
              submission_key: null,
              own: true,
            },
          },
        },
      });
    });
    expect(local()).toContain('"2"');
  });

  it("waits for a Skicka still being checked when Back comes first", async () => {
    vi.useFakeTimers();
    const a = actions();
    let checked!: (v: unknown) => void;
    a.dryRun.mockImplementationOnce(
      () => new Promise((resolve) => (checked = resolve)),
    );
    const before = view();
    const old = render(<ReportForm env="demo" view={before} actions={a} />);
    fillAll();
    send();
    old.unmount(); // Back while the dry run is on its way
    render(<ReportForm env="demo" view={before} actions={a} />);
    expect(screen.getAllByText("Hämtar senaste versionen…")).not.toHaveLength(
      0,
    );
    await act(async () => {});
    expect(refresh).not.toHaveBeenCalled();
    await act(async () => {
      checked({ ok: true, data: { ok: true, refusals: [], warnings: [] } });
    });
    expect(a.submitReport).toHaveBeenCalledTimes(1);
    expect(refresh).toHaveBeenCalled();
  });

  it("reads a view again that holds another draft version than the last one this tab saved", async () => {
    vi.useFakeTimers();
    const a = actions();
    const first = render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    first.unmount();
    // a page read before that save answered, shown for the first time
    render(<ReportForm env="demo" view={view()} actions={a} />);
    await act(async () => {});
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("does not let a retry overwrite the copy another form wrote since", async () => {
    vi.useFakeTimers();
    const a = actions();
    a.saveDraft.mockImplementation(() => fail(502)); // offline
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    const key = Object.keys(window.localStorage).find((k) =>
      k.startsWith("arsrapport:"),
    )!;
    window.localStorage.setItem(
      key,
      JSON.stringify({
        data: { rabbits: { "2": { val: "kvar" } } },
        updated_at: null,
        revision: null,
        writer: "a form mounted later",
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5100); // the retry
    });
    expect(local()).toContain('"2"');
  });

  it("offers Ladda om sidan when a write on its way does not answer", async () => {
    vi.useFakeTimers();
    const a = actions();
    a.saveDraft.mockImplementationOnce(() => new Promise(() => {}));
    const before = view();
    const old = render(<ReportForm env="demo" view={before} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    old.unmount();
    render(<ReportForm env="demo" view={before} actions={a} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(10_000);
    });
    expect(screen.getByRole("button", { name: "Ladda om sidan" })).toBeTruthy();
  });

  it("takes only the view its own reload brings, not one another refresh brought meanwhile", async () => {
    vi.useFakeTimers();
    const a = actions();
    const later = answerLater();
    a.saveDraft.mockImplementationOnce(() => later.call);
    const before = view();
    const old = render(<ReportForm env="demo" view={before} actions={a} />);
    choose(1, "Finns kvar");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    old.unmount();
    const { rerender } = render(
      <ReportForm env="demo" view={before} actions={a} />,
    );
    rerender(<ReportForm env="demo" view={view()} actions={a} />); // read before the save
    expect(screen.getAllByText("Hämtar senaste versionen…")).not.toHaveLength(
      0,
    );
    await act(async () => {
      later.answer();
    });
    rerender(
      <ReportForm
        env="demo"
        view={savedDraft({ "1": { val: "kvar" } })}
        actions={a}
      />,
    );
    expect(screen.queryByText("Hämtar senaste versionen…")).toBeNull();
    expect(checked(1)).toBe(true);
  });

  it("does not read the page again on Back when nothing was saved from it", async () => {
    const a = actions();
    const before = view();
    render(<ReportForm env="demo" view={before} actions={a} />).unmount();
    render(<ReportForm env="demo" view={before} actions={a} />);
    await act(async () => {});
    expect(refresh).not.toHaveBeenCalled();
  });

  it("an error link clears the search and filter and focuses the control that needs input", async () => {
    const a = actions();
    a.dryRun.mockImplementation(() =>
      ok({
        ok: false,
        refusals: [{ individual_id: 2, code: "vikt_saknas", message: "x" }],
        warnings: [],
      }),
    );
    const many = Array.from({ length: 15 }, (_, i) => rabbit(i + 1));
    render(
      <ReportForm env="demo" view={view({ rabbits: many })} actions={a} />,
    );
    choose(2, "Finns kvar");
    send();
    const link = await screen.findByRole("link", { name: /G9001-2/ });
    fireEvent.change(screen.getByLabelText("Hitta en kanin"), {
      target: { value: "Kanin1" },
    });
    expect(screen.queryByRole("group", { name: /G9001-2\b/ })).toBeNull();
    fireEvent.click(link);
    await waitFor(() =>
      expect(document.activeElement).toBe(
        within(row(2)).getByLabelText("Vikt"),
      ),
    );
    expect(
      (screen.getByLabelText("Hitta en kanin") as HTMLInputElement).value,
    ).toBe("");
  });

  it("says what a half-filled death lacks and drops the row error when the row is edited", async () => {
    const a = actions();
    a.dryRun.mockImplementation(() =>
      ok({
        ok: false,
        refusals: [{ individual_id: 2, code: "inte_klar", message: "x" }],
        warnings: [],
      }),
    );
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(2, "Död");
    send();
    const box = (await screen.findByText("1 kanin är inte klara")).closest(
      "div",
    )!;
    expect(box.textContent).toContain("Välj månad.");
    expect(within(row(2)).getByText("Välj månad.")).toBeTruthy();
    choose(2, "Finns kvar");
    expect(screen.queryByText("1 kanin är inte klara")).toBeNull();
    expect(within(row(2)).queryByText("Välj månad.")).toBeNull();
  });

  it("repeats the save state in the sticky bar, hidden from screen readers", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    const line = screen.getByText("Sparas medan du skriver");
    expect(line.getAttribute("aria-hidden")).toBe("true");
  });

  it("puts Skicka after the rabbit list in the DOM", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    const send = screen.getByRole("button", { name: "Skicka årsrapporten" });
    expect(
      row(2).compareDocumentPosition(send) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("leaves focus alone when an edit clears one of several errors", async () => {
    const a = actions();
    a.dryRun.mockImplementation(() =>
      ok({
        ok: false,
        refusals: [
          { individual_id: 1, code: "vikt_saknas", message: "x" },
          { individual_id: 2, code: "vikt_saknas", message: "x" },
        ],
        warnings: [],
      }),
    );
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Finns kvar");
    choose(2, "Finns kvar");
    send();
    const box = (await screen.findByText("2 kaniner är inte klara")).closest(
      "div",
    )!;
    await waitFor(() => expect(document.activeElement).toBe(box));
    const weight = within(row(1)).getByLabelText("Vikt");
    weight.focus();
    fireEvent.change(weight, { target: { value: "3" } });
    expect(screen.getByText("1 kanin är inte klara")).toBeTruthy();
    expect(document.activeElement).toBe(weight);
  });

  it("shows Dragen tillbaka after a withdrawal and locks the confirmation while it runs", async () => {
    const a = actions();
    let release: (v: unknown) => void = () => {};
    a.withdrawReport.mockImplementation(
      () => new Promise((r) => (release = r)),
    );
    render(
      <ReportForm
        env="demo"
        view={view({ report: submittedReport() })}
        actions={a}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Dra tillbaka" }));
    expect(
      screen.getByText("Vill du bara rätta något? Använd Ändra i stället."),
    ).toBeTruthy();
    expect(
      screen
        .getByRole("button", { name: "Dra tillbaka rapporten" })
        .className.includes("confirmDanger"),
    ).toBe(true);
    fireEvent.click(
      screen.getByRole("button", { name: "Dra tillbaka rapporten" }),
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Dra tillbaka rapporten",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    await act(async () => {
      release({
        ok: true,
        data: {
          draft: {
            data: { rabbits: {} },
            updated_at: "2026-12-31T10:00:03+00:00",
          },
        },
      });
    });
    expect(
      await screen.findAllByText(/Dragen tillbaka .* Inte inskickad/),
    ).not.toHaveLength(0);
  });

  it("waits for the refreshed view after its own Skicka and Dra tillbaka, so neither sends a stale revision", async () => {
    const a = actions();
    a.withdrawReport.mockImplementation(() =>
      ok({
        draft: {
          data: { rabbits: {} },
          updated_at: "2027-01-03T14:00:00+00:00",
        },
      }),
    );
    const at = (revision: number) =>
      view({ report: { ...submittedReport(), revision } as never });
    const { rerender } = render(
      <ReportForm env="demo" view={at(0)} actions={a} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Ändra" }));
    fireEvent.change(within(row(1)).getByLabelText("Vikt"), {
      target: { value: "3,1" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Skicka ändringarna" }));
    await screen.findByText(/^Klart\./);
    const button = (name: string | RegExp) =>
      screen.getByRole("button", { name }) as HTMLButtonElement;
    // The receipt is up, but the view still holds revision 0, which the change replaced.
    expect(button("Dra tillbaka").disabled).toBe(true);
    expect(button("Ändra").disabled).toBe(true);
    rerender(<ReportForm env="demo" view={at(1)} actions={a} />);
    expect(button("Dra tillbaka").disabled).toBe(false);
    fireEvent.click(button("Dra tillbaka"));
    fireEvent.click(button("Dra tillbaka rapporten"));
    await waitFor(() => expect(a.withdrawReport).toHaveBeenCalledTimes(1));
    expect(a.withdrawReport.mock.calls[0][2]).toBe(1);
    // The form is back, but the view still holds the withdrawn report: Skicka waits for the one without it.
    expect(
      (
        (await screen.findByRole("button", {
          name: /^Skicka/,
        })) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
    rerender(<ReportForm env="demo" view={view()} actions={a} />);
    expect(button(/^Skicka/).disabled).toBe(false);
  });

  it("adds a litter from Kullar under Y and confirms a preliminary count", async () => {
    const preliminary = {
      id: 7,
      litter_number: null,
      birth_date: "2026-05-10",
      mother: "G9001-1",
      father: "G9001-3",
      litter_size: 5,
      litter_size6w: 5,
      preliminary: true,
    };
    const a = actions();
    const changed = { ...preliminary, litter_size6w: 4, preliminary: false };
    const changeLitter = vi.fn(() => ok({ id: 7, litters: [changed] }));
    const withLitters: ReportActions = {
      ...a,
      addLitter: vi.fn() as never,
      getFathers: vi.fn(() => ok({ hanar: [] })) as never,
      getMothers: vi.fn(() => ok({ honor: [] })) as never,
      changeLitter: changeLitter as never,
    };
    const shown = view({ litters: [preliminary] });
    render(<ReportForm env="demo" view={shown} actions={withLitters} />);
    expect(screen.getAllByText(/\(preliminärt\)/).length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Lägg till kull" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Bekräfta antalet" }));
    fireEvent.change(screen.getByLabelText("Levande vid 6 veckor"), {
      target: { value: "4" },
    });
    // the dialog's own button is the last one with the name
    const buttons = screen.getAllByRole("button", { name: "Bekräfta antalet" });
    fireEvent.click(buttons[buttons.length - 1]);
    await waitFor(() =>
      expect(changeLitter).toHaveBeenCalledWith(
        "G9001",
        2026,
        7,
        { litter_size6w: 4 },
        "demo",
        undefined,
      ),
    );
    await waitFor(() =>
      expect(screen.queryAllByText(/\(preliminärt\)/)).toHaveLength(0),
    );
    // the litter is written, the view is not: Back reads the page again
    cleanup();
    render(<ReportForm env="demo" view={shown} actions={withLitters} />);
    await act(async () => {}); // the reload asks for the page once the writes on their way have answered
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("lists litters as a table with a summary line", () => {
    const l = (id: number, n: number | null, size: number, pre: boolean) => ({
      id,
      litter_number: n,
      birth_date: "2026-05-10",
      mother: "G9001-1",
      father: null,
      litter_size: size,
      litter_size6w: size - 1,
      preliminary: pre,
    });
    render(
      <ReportForm
        env="demo"
        view={view({ litters: [l(1, 12, 5, false), l(2, null, 3, true)] })}
        actions={actions()}
      />,
    );
    expect(
      screen.getByText(
        "2 kullar, 8 födda, 6 levande vid 6 veckor (preliminärt)",
      ),
    ).toBeTruthy();
    for (const h of [
      "Kull",
      "Född",
      "Mor",
      "Far",
      "Födda",
      "Levande vid 6 veckor",
    ])
      expect(screen.getByRole("columnheader", { name: h })).toBeTruthy();
    const rows = screen.getAllByRole("row");
    expect(rows).toHaveLength(3);
    expect(rows[1].textContent).toContain("12");
    expect(rows[2].textContent).toContain("Får nummer när ett intyg skrivs");
    expect(rows[2].textContent).toContain("(preliminärt)");
    expect(rows[1].textContent).not.toContain("preliminärt");
  });

  it("offers no litter button without the litter actions", () => {
    render(<ReportForm env="demo" view={view()} actions={actions()} />);
    expect(screen.queryByRole("button", { name: "Lägg till kull" })).toBeNull();
  });
});
