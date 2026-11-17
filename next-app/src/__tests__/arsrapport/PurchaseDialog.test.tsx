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

vi.mock("@/app/(app)/stamboken/(dashboard)/inskick/ny/prepare", () => ({
  prepare: vi.fn(async (file: File) => file),
}));

import {
  NOT_IN_STAMBOKEN_TEXT,
  PHOTOS_SENT_TEXT,
  PurchaseDialog,
} from "@/app/(app)/stamboken/(dashboard)/arsrapport/PurchaseDialog";
import { PURCHASE_SENT_TEXT } from "@/app/(app)/stamboken/(dashboard)/arsrapport/lib";

afterEach(cleanup);

const herds = () =>
  Promise.resolve({
    success: true as const,
    herds: [
      { herd: "G9001", herd_name: "Gårdsnamn", is_active: true },
      { herd: "G9002", herd_name: "Säljaren", is_active: true },
      { herd: "GX1", herd_name: null, is_active: true },
    ],
  });

function dialog(
  send = vi.fn(),
  onSent = vi.fn(),
  upload = vi.fn(),
  sendPhotos = vi.fn(),
) {
  render(
    <PurchaseDialog
      open
      year={2025}
      genebankId={1}
      ownHerd="G9001"
      loadHerds={herds}
      send={send}
      sendPhotos={sendPhotos}
      upload={upload}
      onSent={onSent}
      onClose={vi.fn()}
    />,
  );
  return { send, onSent, upload, sendPhotos };
}

const click = () =>
  fireEvent.click(screen.getByRole("button", { name: "Skicka anmälan" }));
const fill = (label: string, value: string) =>
  fireEvent.change(screen.getByLabelText(label), { target: { value } });

describe("PurchaseDialog", () => {
  it("needs the number, the seller and the date before it sends", async () => {
    const { send } = dialog();
    expect(screen.getByRole("dialog", { name: /Anmäl ett köp/ })).toBeTruthy();
    click();
    expect(screen.getByRole("alert").textContent).toBe(
      "Skriv kaninens nummer.",
    );
    fill("Kaninens nummer", " G9002-2501 ");
    click();
    expect(screen.getByRole("alert").textContent).toBe(
      "Välj en besättning i genbanken, eller Utanför genbanken.",
    );
    const box = screen.getByRole("combobox", { name: "Säljarens besättning" });
    fireEvent.mouseDown(box);
    expect(await screen.findByText("G9002 – Säljaren")).toBeTruthy();
    expect(screen.queryByText(/G9001 –/)).toBeNull(); // the buyer's own herd
    fireEvent.click(screen.getByText("G9002 – Säljaren"));
    click();
    expect(screen.getByRole("alert").textContent).toBe("Välj datum för köpet.");
    const day = screen.getByLabelText("Datum för köpet") as HTMLInputElement;
    expect(day.min).toBe("2025-01-01");
    fill("Datum för köpet", "2025-05-14");
    send.mockResolvedValue({
      ok: false,
      problem: { status: 502, title: "", detail: "x" },
    });
    click();
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith({
        number: "G9002-2501",
        from_herd: "G9002",
        date: "2025-05-14",
      }),
    );
  });

  it("says where the notice went once it is sent", async () => {
    const send = vi.fn().mockResolvedValue({
      ok: true,
      data: {
        id: 1,
        number: "G9002-2501",
        from_herd: "GX1",
        date: "2025-05-14",
        state: "ny",
      },
    });
    const { onSent } = dialog(send);
    fill("Kaninens nummer", "G9002-2501");
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    fill("Datum för köpet", "2025-05-14");
    click();
    expect((await screen.findByRole("status")).textContent).toBe(
      PURCHASE_SENT_TEXT,
    );
    expect(send.mock.calls[0][0].from_herd).toBe("utanfor");
    expect(onSent).toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Skicka anmälan" })).toBeNull();
    expect(screen.queryByLabelText("Kaninens nummer")).toBeNull();
  });

  it("sends the photos of a rabbit Stamboken lacks to the genebank manager (S7)", async () => {
    const send = vi.fn().mockResolvedValue({
      ok: false,
      problem: {
        status: 422,
        title: "Kan inte sparas",
        detail: "x",
        extensions: { code: "inte_i_stamboken" },
      },
    });
    let n = 30;
    const upload = vi.fn(async () => ({
      ok: true,
      data: { item_id: 7, document_id: ++n },
    }));
    const sendPhotos = vi.fn().mockResolvedValue({
      ok: true,
      data: {
        id: 1,
        number: "G9002-9999",
        from_herd: "GX1",
        date: "2025-05-14",
        state: "ny",
      },
    });
    const { onSent } = dialog(send, vi.fn(), upload, sendPhotos);
    expect(screen.queryByText(NOT_IN_STAMBOKEN_TEXT)).toBeNull(); // only once the server says so
    fill("Kaninens nummer", "G9002-9999");
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    fill("Datum för köpet", "2025-05-14");
    click();
    expect((await screen.findByRole("status")).textContent).toBe(
      NOT_IN_STAMBOKEN_TEXT,
    );
    // the buyer never registers into the seller's herd (Codex P2): no form for it here
    expect(
      screen.queryByRole("button", { name: "Lägg till från intyget" }),
    ).toBeNull();
    expect(screen.queryByLabelText(/om du har\)$/)).toBeNull(); // the notice's photo field is gone
    const sendThem = () =>
      fireEvent.click(
        screen.getByRole("button", { name: "Skicka till genbanksansvarig" }),
      );
    sendThem();
    expect(screen.getByRole("alert").textContent).toBe(
      "Ladda upp ett foto av intyget.",
    ); // a photo is required
    expect(screen.queryByLabelText("Foto 2 (om du har)")).toBeNull();
    const file = () => new File(["x"], "intyg.jpg", { type: "image/jpeg" });
    fireEvent.change(screen.getByLabelText("Foto 1"), {
      target: { files: [file()] },
    });
    await screen.findByLabelText("Foto 2 (om du har)"); // shown once the first is uploaded
    expect((upload.mock.calls[0] as unknown[])[1]).toBe("inskick");
    sendThem();
    expect(screen.getByRole("alert").textContent).toBe(
      "Välj om fotot visar överlåtelsebeviset eller intyget.",
    );
    fireEvent.click(
      within(
        screen.getByRole("radiogroup", { name: "Vad visar foto 1?" }),
      ).getByLabelText("Intyg"),
    );
    fireEvent.change(screen.getByLabelText("Foto 2 (om du har)"), {
      target: { files: [file()] },
    });
    await screen.findByRole("radiogroup", { name: "Vad visar foto 2?" });
    fireEvent.click(
      within(
        screen.getByRole("radiogroup", { name: "Vad visar foto 2?" }),
      ).getByLabelText("Överlåtelsebevis"),
    );
    sendThem();
    await waitFor(() =>
      expect(sendPhotos).toHaveBeenCalledWith({
        number: "G9002-9999",
        from_herd: "utanfor",
        date: "2025-05-14",
        documents: [
          { id: 31, doc_type: "intyg" },
          { id: 32, doc_type: "bevis" },
        ],
      }),
    );
    expect((await screen.findByRole("status")).textContent).toBe(
      PHOTOS_SENT_TEXT,
    );
    expect(onSent).toHaveBeenCalled();
    expect(send).toHaveBeenCalledTimes(1); // the notice was not sent again
  });

  it("sends a photo of the proof or the certificate once it is uploaded, with what it shows", async () => {
    let uploaded: (v: unknown) => void = () => undefined;
    const upload = vi.fn(
      () =>
        new Promise((resolve) => {
          uploaded = resolve;
        }),
    );
    const send = vi.fn().mockResolvedValue({
      ok: true,
      data: {
        id: 1,
        number: "G9002-2501",
        from_herd: "GX1",
        date: "2025-05-14",
        state: "ny",
      },
    });
    dialog(send, vi.fn(), upload);
    fill("Kaninens nummer", "G9002-2501");
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    fill("Datum för köpet", "2025-05-14");
    const file = new File(["x"], "bevis.jpg", { type: "image/jpeg" });
    fireEvent.change(
      screen.getByLabelText(
        "Foto av överlåtelsebeviset eller intyget (om du har)",
      ),
      { target: { files: [file] } },
    );
    await waitFor(() => expect(upload).toHaveBeenCalled());
    expect((upload.mock.calls[0] as unknown[])[0]).toBeInstanceOf(FormData);
    expect(
      (
        screen.getByRole("button", {
          name: "Skicka anmälan",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true); // waits for the photo
    uploaded({ ok: true, data: { item_id: 7, document_id: 31 } });
    expect((await screen.findByRole("status")).textContent).toBe(
      "Fotot är uppladdat.",
    );
    click();
    expect(screen.getByRole("alert").textContent).toBe(
      "Välj om fotot visar överlåtelsebeviset eller intyget.",
    );
    expect(send).not.toHaveBeenCalled();
    fireEvent.click(screen.getByLabelText("Intyg"));
    click();
    await waitFor(() =>
      expect(send).toHaveBeenCalledWith({
        number: "G9002-2501",
        from_herd: "utanfor",
        date: "2025-05-14",
        document_id: 31,
        doc_type: "intyg",
      }),
    );
  });

  it("asks for the photo again when the server no longer takes it", async () => {
    const upload = vi
      .fn()
      .mockResolvedValue({ ok: true, data: { item_id: 7, document_id: 31 } });
    const send = vi.fn().mockResolvedValue({
      ok: false,
      problem: {
        status: 409,
        title: "Konflikt",
        detail: "Fotot kan inte användas längre. Ladda upp det igen.",
        extensions: { field: "photo" },
      },
    });
    dialog(send, vi.fn(), upload);
    fill("Kaninens nummer", "G9002-2501");
    fireEvent.click(screen.getByLabelText("Utanför genbanken"));
    fill("Datum för köpet", "2025-05-14");
    fireEvent.change(
      screen.getByLabelText(
        "Foto av överlåtelsebeviset eller intyget (om du har)",
      ),
      {
        target: {
          files: [new File(["x"], "bevis.jpg", { type: "image/jpeg" })],
        },
      },
    );
    await screen.findByText("Fotot är uppladdat.");
    fireEvent.click(screen.getByLabelText("Överlåtelsebevis"));
    click();
    expect((await screen.findByRole("alert")).textContent).toBe(
      "Fotot kan inte användas längre. Ladda upp det igen.",
    );
    expect(screen.queryByLabelText("Överlåtelsebevis")).toBeNull();
    expect(send.mock.calls[0][0]).toMatchObject({
      document_id: 31,
      doc_type: "bevis",
    });
  });
});
