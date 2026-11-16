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
  getColors: vi.fn(async () => ({ ok: true, data: { farger: ["viltgrå"] } })),
}));
vi.mock("@/app/(app)/stamboken/(dashboard)/inskick/ny/prepare", () => ({
  prepare: async (file: File) => file,
}));

import { AddRabbitDialog } from "@/app/(app)/stamboken/(dashboard)/arsrapport/AddRabbit";
import {
  findRabbit,
  registerRabbit,
  uploadPhoto,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/rabbitActions";

const KEY = "arsrapport:kanin:link:G9001:2025";
const upload = vi.mocked(uploadPhoto);
const register = vi.mocked(registerRabbit);
const find = vi.mocked(findRabbit);

beforeEach(() => localStorage.clear());
afterEach(async () => {
  cleanup();
  // a closed dialog's history.back() lands as a popstate later: not in the next test
  await new Promise((resolve) => setTimeout(resolve, 20));
  vi.clearAllMocks();
  find.mockImplementation(async () => undefined);
});

const input = (label: RegExp | string) => screen.getByLabelText(label);
const type = (label: RegExp | string, value: string) =>
  fireEvent.change(input(label), { target: { value } });
const photoFile = () =>
  new File([new Uint8Array([0xff, 0xd8, 0xff])], "intyg.jpg", {
    type: "image/jpeg",
  });
const choosePhoto = () =>
  fireEvent.change(input("Foto av intyget"), {
    target: { files: [photoFile()] },
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
});

describe("Back", () => {
  it("closes at once when nothing is typed", () => {
    const onClose = open();
    back();
    expect(onClose).toHaveBeenCalledWith([]);
  });

  it("asks Spara som utkast eller släng? once something is typed, and the draft comes back", async () => {
    const onClose = open();
    type(/^Namn/, "Kulla");
    back();
    expect(
      screen.getByText("Spara som utkast eller släng?"),
    ).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));
    expect(onClose).toHaveBeenCalledWith([]);
    cleanup();
    open();
    expect(input(/^Namn/)).toHaveValue("Kulla");
  });

  it("Släng forgets what was typed", () => {
    open();
    type(/^Namn/, "Kulla");
    fireEvent.click(screen.getByRole("button", { name: "Avbryt" }));
    fireEvent.click(screen.getByRole("button", { name: "Släng" }));
    expect(localStorage.getItem(KEY)).toBeNull();
    cleanup();
    open();
    expect(input(/^Namn/)).toHaveValue("");
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
