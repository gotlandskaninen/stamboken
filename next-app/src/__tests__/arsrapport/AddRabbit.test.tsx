import "@testing-library/jest-dom/vitest";
import "@/i18n";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

// "Lägg till kanin från intyget" (4b Task 4): the shared registration form in the report's wrapper.
vi.mock("@/app/(app)/stamboken/(dashboard)/arsrapport/rabbitActions", () => ({
  uploadPhoto: vi.fn(),
  registerRabbit: vi.fn(),
  findRabbit: vi.fn(async () => undefined),
  getFormSetup: vi.fn(async () => ({
    ok: true,
    data: { farger: ["viltgrå"], aktor: "code-12" },
  })),
  suggestNumber: vi.fn(async () => null),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inskick/ny/prepare", () => ({
  prepare: vi.fn(async (file: File) => file),
}));

import { AddRabbitDialog } from "@/app/(app)/stamboken/(dashboard)/arsrapport/AddRabbit";
import { prepare } from "@/app/(app)/stamboken/(dashboard)/inskick/ny/prepare";
import {
  findRabbit,
  getFormSetup,
  registerRabbit,
  suggestNumber,
  uploadPhoto,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/rabbitActions";

const KEY = "arsrapport:kanin:code-12:G9001:2025"; // the link's code 12: a draft is the actor's own
const upload = vi.mocked(uploadPhoto);
const register = vi.mocked(registerRabbit);
const find = vi.mocked(findRabbit);
const setup = vi.mocked(getFormSetup);
const suggest = vi.mocked(suggestNumber);
const prepared = vi.mocked(prepare);

beforeEach(() => localStorage.clear());
afterEach(async () => {
  cleanup();
  // a closed dialog's history.back() lands as a popstate later: not in the next test
  await new Promise((resolve) => setTimeout(resolve, 20));
  vi.clearAllMocks();
  find.mockImplementation(async () => undefined);
  setup.mockImplementation(async () => ({
    ok: true,
    data: { farger: ["viltgrå"], aktor: "code-12" },
  }));
  suggest.mockImplementation(async () => null);
  prepared.mockImplementation(async (file: File) => file);
});

const input = (label: RegExp | string) => screen.getByLabelText(label);
const type = (label: RegExp | string, value: string) =>
  fireEvent.change(input(label), { target: { value } });
const photoFile = (name = "intyg.jpg") =>
  new File([new Uint8Array([0xff, 0xd8, 0xff])], name, {
    type: "image/jpeg",
  });
const choosePhoto = (file = photoFile()) =>
  fireEvent.change(input("Foto av intyget"), {
    target: { files: [file] },
  });
// the browser's Back: the event comes from outside React
const back = () =>
  act(() => {
    window.dispatchEvent(new PopStateEvent("popstate"));
  });
const uploaded = (item_id: number) =>
  ({ ok: true, data: { item_id, document_id: item_id + 100 } }) as const;

function open(onClose = vi.fn()) {
  render(<AddRabbitDialog herd="G9001" year={2025} onClose={onClose} />);
  return onClose;
}
// close the open dialog and let its history.back() land before the next one opens
async function closeAll() {
  cleanup();
  await act(() => new Promise((resolve) => setTimeout(resolve, 20)));
}
// open, and wait for the form's setup (colours, the actor, a saved draft)
async function opened(onClose = vi.fn()) {
  open(onClose);
  await waitFor(() => expect(setup).toHaveBeenCalled());
  await act(async () => {});
  return onClose;
}
const pending = <T,>() => {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => (resolve = r));
  return { promise, resolve };
};

describe("the photo", () => {
  it("a failed upload keeps what was typed, and Försök igen sends only the photo", async () => {
    upload
      .mockResolvedValueOnce({
        ok: false,
        problem: {
          status: 502,
          title: "Bad Gateway",
          detail: "Det gick inte att nå servern. Försök igen.",
        },
      })
      .mockResolvedValueOnce(uploaded(7));
    open();
    type(/^Namn/, "Kulla");
    type(/^Individnummer på pappret/, "G9001-2511");
    choosePhoto();
    expect(
      await screen.findByText(/Det gick inte att nå servern/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spara" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Fotot är uppladdat.")).toBeInTheDocument();
    expect(upload).toHaveBeenCalledTimes(2);
    expect(upload.mock.calls[1][2].get("file")).toBe(
      upload.mock.calls[0][2].get("file"),
    );
    expect(register).not.toHaveBeenCalled();
    expect(input(/^Namn/)).toHaveValue("Kulla");
    expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-2511");
    expect(screen.getByRole("button", { name: "Spara" })).toBeEnabled();
  });

  it("a refusal shows the server's words, the rate limit's too", async () => {
    const limit =
      "Du har laddat upp många foton den senaste timmen. Fortsätt efter kl. 15.40. Det du skrivit är sparat.";
    upload.mockResolvedValueOnce({
      ok: false,
      problem: { status: 429, title: "För många foton", detail: limit },
    });
    open();
    choosePhoto();
    expect(await screen.findByText(limit, { exact: false })).toBeVisible();
  });

  // Codex P1: a photo replaced while it is still being prepared is never sent, whichever finishes first
  it.each([
    ["the replaced one", ["a", "b"]],
    ["the new one", ["b", "a"]],
  ])(
    "only the last photo chosen is sent and registered, when %s is prepared first",
    async (_, order) => {
      const a = photoFile("a.jpg");
      const b = photoFile("b.jpg");
      const ready = { a: pending<File>(), b: pending<File>() };
      prepared.mockImplementation((file) =>
        file === a ? ready.a.promise : ready.b.promise,
      );
      upload.mockResolvedValueOnce(uploaded(8));
      register.mockResolvedValueOnce({
        ok: true,
        data: { id: 51, number: "G9001-2511", item_id: 8, listed: true },
      });
      const onClose = open();
      choosePhoto(a);
      choosePhoto(b);
      for (const which of order as ("a" | "b")[])
        await act(async () => ready[which].resolve(which === "a" ? a : b));
      expect(
        await screen.findByText("Fotot är uppladdat."),
      ).toBeInTheDocument();
      expect(upload).toHaveBeenCalledTimes(1);
      expect(upload.mock.calls[0][2].get("file")).toBe(b);
      type(/^Individnummer på pappret/, "G9001-2511");
      type(/^Intygsnummer/, "P-2511");
      type(/^Födelsedatum/, "2025-05-10");
      type(/^Mor/, "G9001-2411");
      type(/^Far(?!-)/, "G9001-2412");
      fireEvent.click(screen.getByRole("button", { name: "Spara" }));
      await waitFor(() => expect(onClose).toHaveBeenCalled());
      expect(register.mock.calls[0][2]).toMatchObject({ item_id: 8 });
    },
  );
});

describe("Back", () => {
  it("closes at once when nothing is typed", () => {
    const onClose = open();
    back();
    expect(onClose).toHaveBeenCalledWith([]);
  });

  it("asks Spara som utkast eller släng? once something is typed, and the draft comes back", async () => {
    const onClose = await opened();
    type(/^Namn/, "Kulla");
    back();
    expect(
      screen.getByText("Spara som utkast eller släng?"),
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));
    expect(onClose).toHaveBeenCalledWith([]);
    await closeAll();
    await opened();
    expect(input(/^Namn/)).toHaveValue("Kulla");
  });

  it("Släng forgets what was typed", async () => {
    await opened();
    type(/^Namn/, "Kulla");
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    fireEvent.click(screen.getByRole("button", { name: "Släng" }));
    expect(localStorage.getItem(KEY)).toBeNull();
    await closeAll();
    await opened();
    expect(input(/^Namn/)).toHaveValue("");
  });
});

// Finding 5: a shared computer keeps nothing unless asked, and only the actor's own, for a week, without the photo.
describe("the draft in the browser", () => {
  it("is not kept while typing, nor after a failed upload", async () => {
    upload.mockResolvedValueOnce({
      ok: false,
      problem: { status: 502, title: "Bad Gateway", detail: "Nere." },
    });
    await opened();
    type(/^Namn/, "Kulla");
    choosePhoto();
    await screen.findByText(/Nere\./);
    expect(input(/^Namn/)).toHaveValue("Kulla"); // kept in memory for Försök igen
    expect(localStorage.length).toBe(0);
  });

  it("is kept on Spara som utkast without the photo, and asks for the photo again", async () => {
    upload.mockResolvedValueOnce(uploaded(7));
    await opened();
    choosePhoto();
    await screen.findByText("Fotot är uppladdat.");
    type(/^Namn/, "Kulla");
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));
    const stored = localStorage.getItem(KEY)!;
    expect(stored).toContain("Kulla");
    expect(stored).not.toMatch(/item_id|photo|"7"/);
    await closeAll();
    await opened();
    expect(input(/^Namn/)).toHaveValue("Kulla");
    expect(
      screen.getByText(
        "Utkastet är tillbaka. Ladda upp fotot av intyget igen.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Spara" })).toBeDisabled();
  });

  it("is another actor's own: a different code or account does not get it", async () => {
    await opened();
    type(/^Namn/, "Kulla");
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));
    await closeAll();
    setup.mockImplementation(async () => ({
      ok: true,
      data: { farger: [], aktor: "code-13" },
    }));
    await opened();
    expect(input(/^Namn/)).toHaveValue("");
    expect(localStorage.getItem(KEY)).not.toBeNull(); // still there for code 12
  });

  it("is gone after seven days", async () => {
    const old = Date.now() - 8 * 24 * 3600 * 1000;
    localStorage.setItem(
      KEY,
      JSON.stringify({
        saved_at: old,
        drafts: [{ id: 1, form: { name: "Kulla" }, where: null }],
      }),
    );
    await opened();
    expect(input(/^Namn/)).toHaveValue("");
    expect(localStorage.getItem(KEY)).toBeNull();
  });
});

describe("the lookups", () => {
  it("says Finns inte i Stamboken only when the rabbit does not exist", async () => {
    find.mockImplementation(async () => undefined); // a 401 or 403: nothing to say
    open();
    type(/^Mor/, "G9001-2411");
    await waitFor(() =>
      expect(find).toHaveBeenCalledWith("G9001", 2025, "G9001-2411", undefined),
    );
    await act(async () => {}); // the answer is in
    expect(screen.queryByText("Finns inte i Stamboken.")).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: "Lägg till modern från hennes intyg nu",
      }),
    ).toBeNull();
  });

  it("the mother's litters fill in the date, the father and the counts", async () => {
    find.mockImplementation(async (_h, _y, number) =>
      number === "G9001-2411"
        ? {
            name: "Mor",
            color: null,
            mother: null,
            father: null,
            litters: [
              {
                id: 5,
                birth_date: "2025-05-10",
                father: "G9001-2412",
                litter_size: 5,
                litter_size6w: 4,
              },
            ],
          }
        : undefined,
    );
    open();
    type(/^Mor/, "G9001-2411");
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "Kull" }));
    fireEvent.click(
      screen.getByRole("option", {
        name: "Född 2025-05-10, far G9001-2412, 5 födda",
      }),
    );
    expect(input(/^Födelsedatum/)).toHaveValue("2025-05-10");
    expect(input(/^Far(?!-)/)).toHaveValue("G9001-2412");
    expect(input(/^Antal födda/)).toHaveValue(5);
    expect(input(/^Levande i kullen/)).toHaveValue(4);
  });

  const withLitter = (litter: Record<string, unknown>) =>
    find.mockImplementation(async (_h, _y, number) =>
      number === "G9001-2411"
        ? {
            name: "Mor",
            color: null,
            mother: null,
            father: null,
            litters: [
              {
                id: 5,
                birth_date: "2025-05-10",
                father: "G9001-2412",
                litter_size: 5,
                litter_size6w: 5,
                ...litter,
              },
            ],
          }
        : undefined,
    );
  const pickTheLitter = async () => {
    fireEvent.mouseDown(await screen.findByRole("combobox", { name: "Kull" }));
    fireEvent.click(screen.getByRole("option", { name: /^Född 2025-05-10/ }));
  };

  it("a preliminary count is asked for, not copied from the litter", async () => {
    withLitter({ preliminary: true });
    open();
    type(/^Mor/, "G9001-2411");
    await pickTheLitter();
    expect(input(/^Levande i kullen/)).toHaveValue(null);
    expect(input(/^Levande i kullen/)).toBeRequired();
    expect(
      screen.getByText(
        "Kullens antal är preliminärt. Skriv antalet som står på intyget.",
      ),
    ).toBeInTheDocument();
  });

  // Finding 6
  it("a chosen litter brings Stamboken's number, filled in only where nothing is typed", async () => {
    withLitter({});
    suggest.mockImplementation(async () => "G9001-2511");
    open();
    type(/^Mor/, "G9001-2411");
    await pickTheLitter();
    await waitFor(() =>
      expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-2511"),
    );
    expect(suggest).toHaveBeenCalledWith("G9001", 2025, 5, undefined);
    await closeAll();
    open();
    type(/^Individnummer på pappret/, "G9001-2521"); // as the paper says
    type(/^Mor/, "G9001-2411");
    await pickTheLitter();
    expect(
      await screen.findByText(
        "Som det står på intyget. Stamboken föreslår G9001-2511.",
      ),
    ).toBeInTheDocument();
    expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-2521");
  });
});

// Finding 1: an answer belongs to the form that asked, and a registration in progress cannot be cancelled.
describe("a late answer", () => {
  it("of a cancelled mother's upload never reaches the father's form", async () => {
    find.mockImplementation(async () => null); // both parents missing
    const late = pending<Awaited<ReturnType<typeof uploadPhoto>>>();
    upload.mockImplementationOnce(() => late.promise);
    open();
    type(/^Mor/, "G9001-2411");
    type(/^Far(?!-)/, "G9001-2412");
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Lägg till modern från hennes intyg nu",
      }),
    );
    choosePhoto(); // the mother's photo, still on its way
    await waitFor(() => expect(upload).toHaveBeenCalledTimes(1));
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Lägg till fadern från hans intyg nu",
      }),
    );
    await act(async () => late.resolve(uploaded(7)));
    expect(screen.queryByText("Fotot är uppladdat.")).toBeNull();
    expect(screen.getByRole("button", { name: "Spara" })).toBeDisabled();
  });

  it("of a parent's registration: Avbryt waits for it, and the kit's form comes back", async () => {
    find.mockImplementation(async () => null);
    upload.mockResolvedValue(uploaded(9));
    const saving = pending<Awaited<ReturnType<typeof registerRabbit>>>();
    register.mockImplementationOnce(() => saving.promise);
    open();
    type(/^Namn/, "Kulla");
    type(/^Mor/, "G9001-2411");
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Lägg till modern från hennes intyg nu",
      }),
    );
    choosePhoto();
    await screen.findByText("Fotot är uppladdat.");
    type(/^Intygsnummer/, "P-2411");
    type(/^Födelsedatum/, "2024-05-01");
    type(/^Mor/, "G9001-2201");
    type(/^Far(?!-)/, "G9001-2202");
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(register).toHaveBeenCalled());
    expect(screen.getByRole("button", { name: "Avbryt" })).toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Stäng" })); // waits too
    expect(screen.queryByText("Spara som utkast eller släng?")).toBeNull();
    await act(async () =>
      saving.resolve({
        ok: true,
        data: { id: 50, number: "G9001-2411", item_id: 9, listed: true },
      }),
    );
    await waitFor(() => expect(input(/^Namn/)).toHaveValue("Kulla"));
    expect(input(/^Mor/)).toHaveValue("G9001-2411");
  });
});

describe("a missing parent", () => {
  it("is added from her own certificate, and the kit's form comes back", async () => {
    let motherIn = false;
    find.mockImplementation(async (_h, _y, number) =>
      number !== "G9001-2411"
        ? undefined
        : motherIn
          ? { name: null, color: null, mother: null, father: null }
          : null,
    );
    upload
      .mockResolvedValueOnce(uploaded(7))
      .mockResolvedValueOnce(uploaded(9));
    register
      .mockResolvedValueOnce({
        ok: true,
        data: { id: 50, number: "G9001-2411", item_id: 9, listed: true },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { id: 51, number: "G9001-2511", item_id: 7, listed: true },
      });
    const onClose = open();
    choosePhoto();
    await screen.findByText("Fotot är uppladdat.");
    type(/^Namn/, "Kulla");
    type(/^Individnummer på pappret/, "G9001-2511");
    type(/^Intygsnummer/, "P-2511");
    type(/^Födelsedatum/, "2025-05-10");
    type(/^Far(?!-)/, "G9001-2412");
    type(/^Mor/, "G9001-2411");
    fireEvent.click(
      await screen.findByRole("button", {
        name: "Lägg till modern från hennes intyg nu",
      }),
    );

    // the mother's own form: her number and sex from the kit's
    expect(
      screen.getByText(
        "Modern till ungen. När hon är sparad visas ungens uppgifter igen.",
      ),
    ).toBeInTheDocument();
    expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-2411");
    expect(input(/^Namn/)).toHaveValue("");
    expect(screen.getByRole("button", { name: "Spara" })).toBeDisabled(); // her own photo first
    choosePhoto();
    await screen.findByText("Fotot är uppladdat.");
    type(/^Intygsnummer/, "P-2411");
    type(/^Födelsedatum/, "2024-05-01");
    type(/^Mor/, "G9001-2201");
    type(/^Far(?!-)/, "G9001-2202");
    fireEvent.click(screen.getByLabelText("Hos mig"));
    motherIn = true;
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));

    // the kit again, as it was typed
    await waitFor(() => expect(input(/^Namn/)).toHaveValue("Kulla"));
    expect(register.mock.calls[0][2]).toMatchObject({
      item_id: 9,
      paper_number: "G9001-2411",
      sex: "female",
    });
    expect(input(/^Mor/)).toHaveValue("G9001-2411");
    expect(input(/^Individnummer på pappret/)).toHaveValue("G9001-2511");
    expect(screen.getByText("Fotot är uppladdat.")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByText("Finns inte i Stamboken.")).toBeNull(),
    );

    fireEvent.click(screen.getByLabelText("Död"));
    fireEvent.click(screen.getByRole("button", { name: "Spara" }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(register.mock.calls[1][2]).toMatchObject({
      item_id: 7,
      mother: "G9001-2411",
      paper_number: "G9001-2511",
      name: "Kulla",
    });
    expect(onClose.mock.calls[0][0]).toEqual([
      [{ id: 50, number: "G9001-2411", item_id: 9, listed: true }, "hos_mig"],
      [{ id: 51, number: "G9001-2511", item_id: 7, listed: true }, "dod"],
    ]);
    expect(localStorage.getItem(KEY)).toBeNull(); // saved: no draft left
  });
});
