import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConfirmChanges } from "@/app/(app)/rapport/andringar/ConfirmChanges";

const api = "/api/v2/rapport/andringar";
const link = window as Window & { __rapportToken?: string };
const fetchMock = vi.fn();
const account = {
  id: 1,
  falt: "konto",
  state: "vantar",
  nu: null,
  nytt: "•••• 1234",
  datum: "2026-11-30",
};
const address = {
  id: 2,
  falt: "adress",
  state: "bekraftad",
  nu: null,
  nytt: null,
  datum: "2026-11-20",
};
const view = { herd: "M1", version: "v1", changes: [account, address] };
const response = (body: unknown, status = 200) => ({
  status,
  ok: status === 200,
  json: async () => body,
});
const post = (fields?: { version: string; konto: boolean }) => ({
  method: "POST",
  credentials: "same-origin",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ token: "12.abc", ...fields }),
});

beforeEach(() => {
  link.__rapportToken = "12.abc";
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => {
  cleanup();
  delete link.__rapportToken;
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("ConfirmChanges", () => {
  it("reads the view on mount and shows pending and confirmed changes", async () => {
    fetchMock.mockResolvedValue(response(view));
    render(
      <React.StrictMode>
        <ConfirmChanges />
      </React.StrictMode>,
    );

    expect(screen.getByRole("status").textContent).toBe("Hämtar ändringarna …");
    expect(await screen.findByText("Nu: Inget")).toBeTruthy();
    expect(screen.getByText("Nytt: •••• 1234")).toBeTruthy();
    expect(screen.getByText("Bekräfta senast 30 november 2026.")).toBeTruthy();
    expect(screen.getByText("Redan bekräftat 20 november 2026")).toBeTruthy();
    expect(fetchMock.mock.calls).toEqual([[api, post()]]);
    expect(link.__rapportToken).toBeUndefined();
  });

  it("sends the displayed version and changes the account only when checked", async () => {
    fetchMock
      .mockResolvedValueOnce(response(view))
      .mockResolvedValueOnce(response({ ...view, version: "v2" }))
      .mockResolvedValueOnce(
        response({
          ...view,
          changes: [{ ...account, state: "bekraftad", nytt: null }, address],
        }),
      );
    render(<ConfirmChanges />);

    const checkbox = await screen.findByRole("checkbox", {
      name: "Jag bekräftar det nya kontot för stödet.",
    });
    expect(checkbox.matches(":checked")).toBe(false);
    const confirm = screen.getByRole("button", { name: "Bekräfta" });
    const stop = screen.getByRole("button", { name: "Det var inte jag" });
    fireEvent.click(confirm);
    expect(confirm.matches(":disabled")).toBe(true);
    expect(stop.matches(":disabled")).toBe(true);
    const accountPending =
      "Klart. Ändringarna är sparade. Kontot ändras inte förrän du har kryssat i rutan.";
    expect(await screen.findByText(accountPending)).toBeTruthy();
    fireEvent.click(checkbox);
    fireEvent.click(confirm);
    expect(
      await screen.findByText("Klart. Ändringarna är sparade."),
    ).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(fetchMock.mock.calls).toEqual([
      [api, post()],
      [api + "/bekrafta", post({ version: "v1", konto: false })],
      [api + "/bekrafta", post({ version: "v2", konto: true })],
    ]);
  });

  it("stops the changes on click and shows the returned view", async () => {
    fetchMock.mockResolvedValueOnce(response(view)).mockResolvedValueOnce(
      response({
        ...view,
        changes: [{ ...account, state: "inte_jag", nu: null, nytt: null }],
      }),
    );
    render(<ConfirmChanges />);
    fireEvent.click(
      await screen.findByRole("button", { name: "Det var inte jag" }),
    );

    expect(
      await screen.findByText(
        "Ändringarna är stoppade. Genbanksansvarig ser att det inte var du.",
      ),
    ).toBeTruthy();
    expect(screen.getByText("Det var inte jag")).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
    expect(fetchMock.mock.calls).toEqual([
      [api, post()],
      [api + "/inte-jag", post()],
    ]);
  });

  it("shows the expired link message for lank_ogiltig", async () => {
    fetchMock.mockResolvedValue(response({ code: "lank_ogiltig" }, 403));
    render(<ConfirmChanges />);
    expect(
      await screen.findByText(
        "Länken gäller inte längre. Har du fått ett nyare mejl från Stamboken? Använd länken i det.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("asks the member to reopen the email when there is no token", () => {
    delete link.__rapportToken;
    render(<ConfirmChanges />);
    expect(screen.getByRole("status").textContent).toBe(
      "Öppna länken i mejlet igen.",
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("shows the conflict detail and reads the new view before confirming again", async () => {
    const detail = "Uppgifterna har ändrats.";
    fetchMock
      .mockResolvedValueOnce(response(view))
      .mockResolvedValueOnce(response({ detail }, 409))
      .mockResolvedValueOnce(
        response({
          ...view,
          version: "v2",
          changes: [{ ...account, nytt: "•••• 9876" }],
        }),
      );
    render(<ConfirmChanges />);
    const checkbox = await screen.findByRole("checkbox");
    fireEvent.click(checkbox);
    fireEvent.click(screen.getByRole("button", { name: "Bekräfta" }));

    expect(await screen.findByText("Nytt: •••• 9876")).toBeTruthy();
    expect(screen.getByRole("status").textContent).toBe(detail);
    expect(checkbox.matches(":checked")).toBe(false);
    expect(fetchMock.mock.calls).toEqual([
      [api, post()],
      [api + "/bekrafta", post({ version: "v1", konto: true })],
      [api, post()],
    ]);
  });

  it("retries a rate-limited confirmation by reading the view", async () => {
    fetchMock
      .mockResolvedValueOnce(response(view))
      .mockResolvedValueOnce(response({}, 429))
      .mockResolvedValueOnce(response(view));
    render(<ConfirmChanges />);
    fireEvent.click(await screen.findByRole("button", { name: "Bekräfta" }));
    expect(
      await screen.findByText("Det gick inte att nå servern. Försök igen."),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(await screen.findByText("Nytt: •••• 1234")).toBeTruthy();
    expect(fetchMock).toHaveBeenLastCalledWith(api, post());
  });
});
