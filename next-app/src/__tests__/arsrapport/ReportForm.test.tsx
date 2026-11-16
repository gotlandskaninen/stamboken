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
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/ReportForm";
import {
  PENDING_SALE_TEXT,
  type Receipt,
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
      kopanmalningar: [
        {
          id: 5,
          number: "G9002-77",
          from_herd: "G9002",
          date: "2026-06-01",
          state: "ny",
        },
        {
          id: 6,
          number: "G9002-78",
          from_herd: "G9002",
          date: "2026-06-02",
          state: "klar",
        },
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
    // an open notice is shown as waiting; a registered one is the rabbit's row
    expect(screen.getByText(/Anmält köp: G9002-77, 1 juni 2026/)).toBeTruthy();
    expect(screen.queryByText(/G9002-78/)).toBeNull();
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
              dag: null,
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
        view={view({ draft: kept })}
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

  it("holds a buyer outside the genebank in memory only: the draft and localStorage never get it", async () => {
    vi.useFakeTimers();
    const a = actions();
    render(<ReportForm env="demo" view={view()} actions={a} />);
    choose(1, "Såld");
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    fireEvent.change(screen.getByLabelText(/Köparens namn/), {
      target: { value: "Ola Köpare" },
    });
    fireEvent.change(screen.getByLabelText(/^Ort/), {
      target: { value: "Visby" },
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
});
