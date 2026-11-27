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
  type PaperProps,
  type ReportActions,
  forgetTabWrites,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/ReportForm";
import type {
  Receipt,
  ReportView,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";
import { rabbit, view } from "./fixtures";
import "@/i18n";

const receipt: Receipt = {
  submission_id: 1,
  report_id: 1,
  created_at: "2027-01-03T13:32:00+00:00",
  source: "paper",
  summary: { kvar: 1, doda: 0, salda: 0, ej_angivna: 1 },
  matrikel: [],
  warnings: [],
};
const ok = <T,>(data: T) => Promise.resolve({ ok: true as const, data });
const fail = (status: number) =>
  Promise.resolve({
    ok: false as const,
    problem: { status, title: "t", detail: "x", extensions: {} },
  });

const actions = () =>
  ({
    saveDraft: vi.fn(() =>
      ok({ updated_at: "2027-01-03T10:00:00+00:00", submission_key: null }),
    ),
    dryRun: vi.fn(() => ok({ ok: true, refusals: [], warnings: [] })),
    submitReport: vi.fn(() => ok(receipt)),
    withdrawReport: vi.fn(),
  }) as unknown as {
    [K in keyof ReportActions]: ReturnType<typeof vi.fn>;
  } & ReportActions;

const paperProps = (over: Partial<PaperProps> = {}): PaperProps => ({
  documentIds: [11, 12],
  intygPending: false,
  archive: vi.fn(() => ok({})) as never,
  leave: vi.fn(),
  ...over,
});
const paperView = (over: Partial<ReportView> = {}): ReportView =>
  view({
    herd: {
      id: 2,
      herd: "G9001",
      name: "Gårdsnamn",
      genebank_id: 1,
      genebank: "Gotlandskanin",
    },
    access: "helper",
    source: "paper",
    rabbits: [rabbit(1), rabbit(2), rabbit(3)],
    item: {
      id: 5,
      received_at: "2027-01-03T10:00:00+00:00",
      state: "tagen",
      account_end: "12",
    },
    ...over,
  });

beforeEach(() => {
  forgetTabWrites(); // module memory of the tab, as after a hard load
  window.scrollTo = vi.fn(); // jsdom does not implement it
  window.localStorage.clear();
  refresh.mockReset();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const typeNumber = (n: string) => {
  const input = screen.getByLabelText("Nummer efter G9001-");
  fireEvent.change(input, { target: { value: n } });
  fireEvent.keyDown(input, { key: "Enter" });
};
const row = (n: number) =>
  // nosemgrep: javascript.lang.security.audit.detect-non-literal-regexp.detect-non-literal-regexp -- n is a test constant, not user input
  screen.getByRole("group", { name: new RegExp(`G9001-${n}\\b`) });
const sendButton = () =>
  screen.getByRole("button", { name: "Skicka och nästa blankett" });
const renderPaper = (v = paperView(), a = actions(), p = paperProps()) => {
  render(<ReportForm env="demo" view={v} actions={a} post={5} paper={p} />);
  return { a, p };
};

describe("ReportForm on paper", () => {
  it("shows the entered and remaining counter and the key help", () => {
    renderPaper();
    expect(screen.getByText("0 inmatade, 3 kvar")).toBeTruthy();
    expect(
      screen.getByText(
        "Enter går vidare. När kaninens val har fokus: 1 Finns kvar, 2 Död, 3 Såld.",
      ),
    ).toBeTruthy();
    typeNumber("1");
    expect(screen.getByText("1 inmatade, 2 kvar")).toBeTruthy();
  });
  it("names the item and defaults the receipt date to the day it came in", () => {
    renderPaper();
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Från blankett · G9001 · Ärende 5",
      }),
    ).toBeTruthy();
    expect((screen.getByLabelText("Mottagen") as HTMLInputElement).value).toBe(
      "2027-01-03",
    );
    expect(screen.getByText("Nuvarande konto slutar på ••12")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Gå till profilen" })).toBeNull();
  });

  it("enters a rabbit by its number, and keys 1 then Enter walk the row", () => {
    renderPaper();
    typeNumber("2");
    expect(row(2)).toBeTruthy();
    const kvar = within(row(2)).getByLabelText("Finns kvar");
    expect(document.activeElement).toBe(kvar);
    fireEvent.keyDown(kvar, { key: "1" });
    expect((kvar as HTMLInputElement).checked).toBe(true);
    const vikt = within(row(2)).getByLabelText("Vikt");
    expect(document.activeElement).toBe(vikt);
    fireEvent.keyDown(vikt, { key: "1" }); // a digit in the field, not a choice
    expect(document.activeElement).toBe(vikt);
    fireEvent.keyDown(vikt, { key: "Enter" });
    expect(document.activeElement).toBe(
      within(row(2)).getByRole("button", { name: "Ej vägd" }),
    );
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    expect(document.activeElement).toBe(within(row(2)).getByLabelText(/^Hull/));
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    expect(document.activeElement).toBe(
      screen.getByLabelText("Nummer efter G9001-"),
    );
  });

  it("takes a full number from another herd as written", () => {
    renderPaper(
      paperView({ rabbits: [rabbit(1), rabbit(2, { number: "G9002-77" })] }),
    );
    const input = screen.getByLabelText("Nummer efter G9001-");
    fireEvent.change(input, { target: { value: "g9002-77" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByRole("group", { name: /G9002-77/ })).toBeTruthy();
  });

  it("walks a dead rabbit's fields with Enter before the next row", () => {
    renderPaper();
    typeNumber("2");
    fireEvent.keyDown(within(row(2)).getByLabelText("Finns kvar"), {
      key: "2",
    });
    const month = within(row(2)).getByLabelText("Månad");
    expect(document.activeElement).toBe(month);
    const step = (label: RegExp | string, tag?: string) => {
      fireEvent.keyDown(document.activeElement!, { key: "Enter" });
      void tag;
      expect(document.activeElement).toBe(
        typeof label === "string"
          ? document.getElementById(label)
          : within(row(2)).getByLabelText(label),
      );
    };
    step(/^Dag/);
    step("slaktad-2-ja");
    step("note-2");
    fireEvent.keyDown(document.activeElement!, { key: "Enter" });
    expect(document.activeElement).toBe(
      screen.getByLabelText("Nummer efter G9001-"),
    );
  });

  it("does not adopt a local copy behind the member-draft gate, and Börja clears it", async () => {
    vi.useFakeTimers();
    window.localStorage.setItem(
      "arsrapport:demo:G9001:2026",
      JSON.stringify({ rabbits: { "1": { val: "kvar", vikt: 2 } } }),
    );
    const a = actions();
    renderPaper(
      paperView({
        draft: {
          data: {} as never,
          updated_at: "2027-01-02T09:00:00+00:00",
          submission_key: null,
          own: false,
        },
      }),
      a,
    );
    expect(
      screen.getAllByText(/Medlemmen har påbörjat rapporten/).length,
    ).toBeGreaterThan(0);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    expect(a.saveDraft).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "Börja från blanketten" }),
    );
    expect(
      window.localStorage.getItem("arsrapport:demo:G9001:2026"),
    ).toBeNull();
    expect(
      (within(row(1)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(false);
  });

  it("Visa alla brings the rows back after the not-done filter", async () => {
    const a = actions();
    a.dryRun.mockImplementationOnce(() =>
      ok({
        ok: false,
        refusals: [
          { individual_id: 2, code: "inte_klar", message: "Välj något." },
        ],
        warnings: [],
      }),
    );
    renderPaper(paperView(), a);
    typeNumber("1");
    fireEvent.click(within(row(1)).getByLabelText("Finns kvar"));
    fireEvent.change(within(row(1)).getByLabelText("Vikt"), {
      target: { value: "2,8" },
    });
    fireEvent.click(sendButton());
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Visa bara dem som inte är klara",
      }),
    );
    expect(screen.queryByRole("group", { name: /G9001-1\b/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Visa alla" }));
    expect(row(1)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Visa alla" })).toBeNull();
  });

  it("says when a number is not there or was entered already", () => {
    renderPaper();
    typeNumber("2399");
    expect(
      screen.getByText(
        "G9001-2399 finns inte bland kaninerna i G9001 den 31 december 2026.",
      ),
    ).toBeTruthy();
    typeNumber("2");
    typeNumber("2");
    expect(screen.getByText(/Redan inmatad på/)).toBeTruthy();
  });

  it("lists the rabbits not on the form and marks them Ej angiven in one go", () => {
    renderPaper();
    typeNumber("1");
    fireEvent.click(within(row(1)).getByLabelText("Finns kvar"));
    expect(
      screen.getByText("Kvar i Stamboken men inte på blanketten (2)"),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", {
        name: "Markera som ej angivna på blanketten",
      }),
    );
    expect(
      screen.getByText("Kvar i Stamboken men inte på blanketten (0)"),
    ).toBeTruthy();
    expect(
      (
        within(row(2)).getByLabelText(
          "Ej angiven på blanketten",
        ) as HTMLInputElement
      ).checked,
    ).toBe(true);
    expect(
      (
        within(row(3)).getByLabelText(
          "Ej angiven på blanketten",
        ) as HTMLInputElement
      ).checked,
    ).toBe(true);
    // the rabbit that is on the form is not marked
    expect(
      (within(row(1)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(true);
  });

  it("sends the item, the dates and the contact changes with ?post=, and leaves on a clean receipt", async () => {
    const { a, p } = renderPaper();
    typeNumber("1");
    fireEvent.click(within(row(1)).getByLabelText("Finns kvar"));
    fireEvent.change(within(row(1)).getByLabelText("Vikt"), {
      target: { value: "2,8" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Markera som ej angivna på blanketten",
      }),
    );
    fireEvent.change(screen.getByLabelText("Telefon"), {
      target: { value: "070-1234567" },
    });
    fireEvent.click(screen.getByLabelText("Nej"));
    fireEvent.click(sendButton());
    await waitFor(() => expect(a.submitReport).toHaveBeenCalledTimes(1));
    const [herd, year, body, env, post] = a.submitReport.mock.calls[0];
    expect([herd, year, env, post]).toEqual(["G9001", 2026, "demo", 5]);
    expect(body).toMatchObject({
      inbox_item_id: 5,
      received_on: "2027-01-03",
      matrikel: {
        telefon: "070-1234567",
        publicering: { ja: false, utom: [] },
      },
      rabbits: {
        "1": { val: "kvar", vikt: 2.8 },
        "2": { val: "ej_angiven" },
        "3": { val: "ej_angiven" },
      },
    });
    expect(body).not.toHaveProperty("signed_on");
    expect(a.dryRun.mock.calls[0][4]).toBe(5);
    await waitFor(() =>
      expect(p.leave).toHaveBeenCalledWith(
        "G9001 inskickad: 1 finns kvar, 1 ej angivna.",
      ),
    );
    expect(refresh).not.toHaveBeenCalled();
  });

  it("refuses a form date later than the day it came in", async () => {
    const { a } = renderPaper();
    typeNumber("1");
    fireEvent.click(within(row(1)).getByLabelText("Finns kvar"));
    fireEvent.change(screen.getByLabelText("Mottagen"), {
      target: { value: "2027-01-01" },
    });
    fireEvent.change(screen.getByLabelText("Blankettens datum"), {
      target: { value: "2027-01-02" },
    });
    fireEvent.click(sendButton());
    expect(
      await screen.findByText(
        "Blankettens datum kan inte vara senare än dagen den kom in.",
      ),
    ).toBeTruthy();
    expect(a.dryRun).not.toHaveBeenCalled();
  });

  it.each(["dry run", "submit"])(
    "keeps the typed buyer after an email refusal at %s",
    async (stage) => {
      const a = actions();
      const message =
        "E-postadressen kan inte användas. Kontrollera den med medlemmen.";
      const code = "epost_kan_inte_anvandas";
      if (stage === "dry run") {
        a.dryRun.mockResolvedValueOnce({
          ok: true,
          data: {
            ok: false,
            refusals: [{ individual_id: null, code, message }],
            warnings: [],
          },
        });
      } else {
        a.submitReport.mockResolvedValueOnce({
          ok: false,
          problem: {
            status: 409,
            title: "Konflikt",
            detail: message,
            extensions: { code, field: "epost" },
          },
        });
      }
      a.getGenebankHerds = vi.fn(async () => ({
        success: true as const,
        herds: [],
      }));
      renderPaper(paperView({ rabbits: [rabbit(1)] }), a);
      typeNumber("1");
      fireEvent.click(within(row(1)).getByLabelText("Såld"));
      fireEvent.click(screen.getByLabelText("Utanför genbanken"));
      fireEvent.click(screen.getByRole("radio", { name: "Ja" })); // the buyer has e-mail (before 2027)
      const buyer = {
        name: "Ola Köpare",
        town: "Visby",
        postal_address: "Testgatan 1",
        email: "ola@example.invalid",
        notice_only: true,
      };
      fireEvent.change(
        within(screen.getByRole("dialog")).getByLabelText(/Köparens namn/),
        {
          target: { value: buyer.name },
        },
      );
      fireEvent.change(
        within(screen.getByRole("dialog")).getByLabelText(/^Ort/),
        {
          target: { value: buyer.town },
        },
      );
      fireEvent.change(
        within(screen.getByRole("dialog")).getByLabelText(/^Postadress/),
        {
          target: { value: buyer.postal_address },
        },
      );
      fireEvent.change(
        within(screen.getByRole("dialog")).getByLabelText(/^E-post/),
        {
          target: { value: buyer.email },
        },
      );
      fireEvent.change(screen.getByLabelText("Månad"), {
        target: { value: "1" },
      });
      fireEvent.click(
        screen.getByRole("button", { name: "Spara försäljningen" }),
      );
      const email = screen.getByLabelText<HTMLInputElement>("E-post");
      fireEvent.change(email, { target: { value: "gammal@example.invalid" } });
      fireEvent.change(screen.getByLabelText("Telefon"), {
        target: { value: "070-1234567" },
      });
      fireEvent.click(sendButton());

      fireEvent.click(await screen.findByRole("link", { name: message }));
      expect(document.activeElement).toBe(email);
      expect(
        screen.getByRole("textbox", { name: "E-post", description: message }),
      ).toBe(email);
      expect(email.getAttribute("aria-invalid")).toBe("true");
      expect(email.value).toBe("gammal@example.invalid");
      expect(refresh).not.toHaveBeenCalled();
      expect(a.submitReport).toHaveBeenCalledTimes(stage === "submit" ? 1 : 0);

      fireEvent.change(email, { target: { value: "ratt@example.invalid" } });
      expect(email.hasAttribute("aria-invalid")).toBe(false);
      fireEvent.click(sendButton());
      await waitFor(() =>
        expect(a.submitReport).toHaveBeenCalledTimes(
          stage === "submit" ? 2 : 1,
        ),
      );
      expect(a.submitReport.mock.calls.at(-1)![2]).toMatchObject({
        rabbits: {
          "1": { val: "sald", sald: { till: "utanfor", kopare: buyer } },
        },
        matrikel: { epost: "ratt@example.invalid", telefon: "070-1234567" },
      });
    },
  );

  it("keeps the matrikel and the buyer out of the draft and localStorage", async () => {
    vi.useFakeTimers();
    const { a } = renderPaper();
    typeNumber("1");
    fireEvent.click(within(row(1)).getByLabelText("Finns kvar"));
    fireEvent.change(screen.getByLabelText("Telefon"), {
      target: { value: "070-1234567" },
    });
    fireEvent.change(screen.getByLabelText("E-post"), {
      target: { value: "x@example.invalid" },
    });
    await vi.advanceTimersByTimeAsync(2500);
    expect(a.saveDraft).toHaveBeenCalled();
    const [, , data, , , , , post] = a.saveDraft.mock.calls.at(-1)!;
    expect(post).toBe(5);
    expect(JSON.stringify(data)).not.toMatch(/matrikel|070-1234567|example/);
    expect(Object.keys(data)).not.toContain("matrikel");
    const stored = Object.values(window.localStorage).join("");
    expect(stored).not.toMatch(/matrikel|070-1234567|example/);
  });

  it("Försök igen sends the frozen body, matrikel and post included, to submitReport only", async () => {
    const a = actions();
    a.submitReport.mockImplementationOnce(() => fail(504));
    renderPaper(paperView(), a);
    typeNumber("1");
    fireEvent.click(within(row(1)).getByLabelText("Finns kvar"));
    fireEvent.change(screen.getByLabelText("Telefon"), {
      target: { value: "070-1234567" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Markera som ej angivna på blanketten",
      }),
    );
    fireEvent.change(within(row(1)).getByLabelText("Vikt"), {
      target: { value: "2,8" },
    });
    fireEvent.click(sendButton());
    const retry = await screen.findByRole("button", { name: "Försök igen" });
    // the form is locked; what is typed now does not change the frozen body
    fireEvent.click(retry);
    await waitFor(() => expect(a.submitReport).toHaveBeenCalledTimes(2));
    expect(a.dryRun).toHaveBeenCalledTimes(1);
    const [first, second] = a.submitReport.mock.calls;
    expect(second[2]).toBe(first[2]);
    expect(second[2].matrikel).toEqual({ telefon: "070-1234567" });
    expect(second[4]).toBe(5);
  });

  it("stays on the receipt when the matrikel took something or skipped it, with no value", async () => {
    const a = actions();
    a.submitReport.mockImplementationOnce(() =>
      ok({
        ...receipt,
        matrikel: ["telefon"],
        warnings: [
          {
            individual_id: null,
            code: "senare_andring",
            message: "Kontrollera blankettens uppgift om adress med medlemmen.",
          },
        ],
      }),
    );
    const { p } = renderPaper(paperView(), a);
    typeNumber("1");
    fireEvent.click(within(row(1)).getByLabelText("Finns kvar"));
    fireEvent.change(within(row(1)).getByLabelText("Vikt"), {
      target: { value: "2,8" },
    });
    fireEvent.change(screen.getByLabelText("Telefon"), {
      target: { value: "070-1234567" },
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: "Markera som ej angivna på blanketten",
      }),
    );
    fireEvent.click(sendButton());
    expect(
      await screen.findByText(/Sparat i matrikeln: telefon\./),
    ).toBeTruthy();
    expect(
      screen.getByText(
        "Kontrollera blankettens uppgift om adress med medlemmen.",
      ),
    ).toBeTruthy();
    expect(screen.getByRole("link", { name: "Nästa blankett" })).toBeTruthy();
    expect(screen.queryByText(/070-1234567/)).toBeNull();
    expect(p.leave).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("shows only the arrival day on the receipt after a paper submission", async () => {
    const a = actions();
    a.submitReport.mockResolvedValueOnce({
      ok: true,
      data: {
        ...receipt,
        created_at: "2027-01-15T11:00:00Z",
        matrikel: ["telefon"],
      },
    });
    renderPaper(paperView({ rabbits: [] }), a);
    fireEvent.change(screen.getByLabelText("Mottagen"), {
      target: { value: "2027-01-12" },
    });
    fireEvent.change(screen.getByLabelText("Telefon"), {
      target: { value: "070-1234567" },
    });
    fireEvent.click(sendButton());
    expect(
      await screen.findByRole("heading", {
        name: "Klart. Årsrapporten för G9001 kom in 12 januari 2027.",
      }),
    ).toBeTruthy();
  });

  it("warns when the typed account ends like the stored one, and shows no stored value but its end", () => {
    renderPaper();
    fireEvent.change(screen.getByLabelText("Kontonummer"), {
      target: { value: "123456712" },
    });
    expect(
      screen.getByText(/Samma slutsiffror som nuvarande konto/),
    ).toBeTruthy();
  });

  it("asks for a clearing number for a bankkonto only", () => {
    renderPaper();
    fireEvent.change(screen.getByLabelText("Clearingnummer"), {
      target: { value: "8327" },
    });
    fireEvent.click(screen.getByLabelText("Plusgiro"));
    expect(screen.queryByLabelText("Clearingnummer")).toBeNull();
    fireEvent.click(screen.getByLabelText("Bankkonto"));
    // the clearing number typed for the other box is gone, not sent with a plusgiro
    expect(
      (screen.getByLabelText("Clearingnummer") as HTMLInputElement).value,
    ).toBe("");
  });

  it("says there is no account when the matrikel has none", () => {
    renderPaper(
      paperView({
        item: {
          id: 5,
          received_at: "2027-01-03T10:00:00+00:00",
          state: "tagen",
          account_end: null,
        },
      }),
    );
    expect(screen.getByText("Inget konto i matrikeln")).toBeTruthy();
  });

  it("says there is an account when its end is too short to show", () => {
    renderPaper(
      paperView({
        item: {
          id: 5,
          received_at: "2027-01-03T10:00:00+00:00",
          state: "tagen",
          account_end: "",
        },
      }),
    );
    expect(screen.getByText("Det finns ett konto i matrikeln")).toBeTruthy();
  });

  it("asks nothing of the form first when the intyg are not done", () => {
    renderPaper(paperView(), actions(), paperProps({ intygPending: true }));
    expect(screen.getByText(/Registrera intygen i ärendet först/)).toBeTruthy();
    expect(screen.queryByLabelText("Mottagen")).toBeNull();
  });

  it("shows a member's draft behind a gate, but not the helper's own", () => {
    const draft = {
      data: { rabbits: { "1": { val: "kvar", vikt: 2.5 } } } as never,
      updated_at: "2027-01-02T09:00:00+00:00",
      submission_key: null,
      own: false,
    };
    const { unmount } = render(
      <ReportForm
        env="demo"
        view={paperView({ draft })}
        actions={actions()}
        post={5}
        paper={paperProps()}
      />,
    );
    expect(
      screen.getByText(/Medlemmen har påbörjat rapporten \(senast/),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Fortsätt på medlemmens utkast" }),
    );
    expect(
      (within(row(1)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(true);
    unmount();
    renderPaper(paperView({ draft: { ...draft, own: true } }));
    expect(screen.queryByText(/Medlemmen har påbörjat/)).toBeNull();
  });

  it("hides the member-draft gate while Back reads the page again, and takes the new view without a draft", async () => {
    vi.useFakeTimers();
    const draft = {
      data: { rabbits: { "1": { val: "kvar", vikt: 2.5 } } } as never,
      updated_at: "2027-01-02T09:00:00+00:00",
      submission_key: null,
      own: false,
    };
    const gated = paperView({ draft });
    const a = actions();
    render(
      <ReportForm
        env="demo"
        view={gated}
        actions={a}
        post={5}
        paper={paperProps()}
      />,
    ).unmount();
    // the same report saved from its ordinary page meanwhile
    const other = render(
      <ReportForm env="demo" view={paperView({ item: null })} actions={a} />,
    );
    fireEvent.click(within(row(1)).getByLabelText("Finns kvar"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(2100);
    });
    other.unmount();
    const { rerender } = render(
      <ReportForm
        env="demo"
        view={gated}
        actions={a}
        post={5}
        paper={paperProps()}
      />,
    );
    await act(async () => {}); // the reload asks for the page once the writes on their way have answered
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByRole("button", { name: "Fortsätt på medlemmens utkast" }),
    ).toBeNull();
    expect(screen.getAllByText("Hämtar senaste versionen…")).not.toHaveLength(
      0,
    );
    // the member sent the report meanwhile: no draft, and no crash on the old gate
    rerender(
      <ReportForm
        env="demo"
        view={paperView()}
        actions={a}
        post={5}
        paper={paperProps()}
      />,
    );
    expect(screen.queryByText(/Medlemmen har påbörjat/)).toBeNull();
  });

  it("starts empty on Börja från blanketten", () => {
    renderPaper(
      paperView({
        draft: {
          data: { rabbits: { "1": { val: "kvar", vikt: 2.5 } } } as never,
          updated_at: "2027-01-02T09:00:00+00:00",
          submission_key: null,
          own: false,
        },
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "Börja från blanketten" }),
    );
    // nothing of the member's draft was taken over
    expect(
      (within(row(1)).getByLabelText("Finns kvar") as HTMLInputElement).checked,
    ).toBe(false);
    expect(
      screen.getByText("Kvar i Stamboken men inte på blanketten (3)"),
    ).toBeTruthy();
  });

  const reported = () =>
    paperView({
      report: {
        id: 1,
        status: "submitted",
        source: "login",
        revision: 4,
        received_at: "2027-01-02T09:00:00+00:00",
        report_date: "2027-01-02",
        on_time: true,
        submitted: { rabbits: { "1": { val: "kvar", vikt: 2.8 } } as never },
        can_change: true,
        can_withdraw: false,
        withdraw_until: null,
        villkor: { hane: true, hona: true, kull: true, i_tid: true },
      },
    });

  it("archives each open form page and leaves, over a report already sent", async () => {
    const p = paperProps();
    renderPaper(reported(), actions(), p);
    expect(
      screen.getByText(/Redan rapporterad den 2 januari 2027/),
    ).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", { name: "Arkivera blanketten" }),
    );
    await waitFor(() => expect(p.leave).toHaveBeenCalled());
    expect(p.archive).toHaveBeenCalledTimes(2);
    expect(p.archive).toHaveBeenNthCalledWith(1, 11);
    expect(p.archive).toHaveBeenNthCalledWith(2, 12);
  });

  it("needs a reason to change a report from paper, and sends its revision", async () => {
    const a = actions();
    renderPaper(reported(), a);
    const change = screen.getByRole("button", { name: "Ändra rapporten" });
    expect((change as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Varför ändras rapporten?"), {
      target: { value: "Ny blankett från medlemmen" },
    });
    fireEvent.click(change);
    fireEvent.click(
      screen.getByRole("button", {
        name: "Markera som ej angivna på blanketten",
      }),
    );
    fireEvent.click(sendButton());
    await waitFor(() => expect(a.submitReport).toHaveBeenCalled());
    expect(a.submitReport.mock.calls[0][2]).toMatchObject({
      revision: 4,
      reason: "Ny blankett från medlemmen",
    });
  });

  it("does not archive when a page cannot be dismissed", async () => {
    const p = paperProps({
      archive: vi.fn().mockResolvedValue({
        ok: false,
        problem: {
          status: 409,
          title: "Konflikt",
          detail: "Sidan är redan arkiverad.",
        },
      }),
    });
    renderPaper(reported(), actions(), p);
    fireEvent.click(
      screen.getByRole("button", { name: "Arkivera blanketten" }),
    );
    expect(await screen.findByText("Sidan är redan arkiverad.")).toBeTruthy();
    expect(p.leave).not.toHaveBeenCalled();
  });

  it("asks a reason of a helper after the last day, and lets the form open", async () => {
    const a = actions();
    renderPaper(
      paperView({
        round: {
          start_date: "2026-12-31",
          deadline: "2027-01-31",
          end_date: "2000-01-01",
          activated: true,
          open: false,
        },
      }),
      a,
    );
    expect(
      screen.getByLabelText("Varför kommer blanketten in efter sista dagen?"),
    ).toBeTruthy();
    expect(screen.getByLabelText("Mottagen")).toBeTruthy();
  });

  it("ends a genebank with no rabbit choices", async () => {
    const a = actions();
    renderPaper(paperView(), a);
    fireEvent.click(screen.getByLabelText("Jag avslutar min besättning"));
    fireEvent.click(screen.getByLabelText(/även avsluta mitt medlemskap/));
    fireEvent.click(sendButton());
    await waitFor(() => expect(a.submitReport).toHaveBeenCalled());
    expect(a.submitReport.mock.calls[0][2]).toMatchObject({
      ending_genbank: true,
      membership_after_end: "avsluta_medlemskap",
    });
  });
});
