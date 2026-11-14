// jest-dom matchers on vitest's expect (this project has no global setup).
import "@testing-library/jest-dom/vitest";
import { StrictMode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";

const { eraseBuyerMock } = vi.hoisted(() => ({ eraseBuyerMock: vi.fn() }));

vi.mock("@/app/(app)/(public)/kopare/ta-bort/actions", () => ({
  eraseBuyer: eraseBuyerMock,
}));

import {
  EraseBuyer,
  takeToken,
} from "@/app/(app)/(public)/kopare/ta-bort/EraseBuyer";

const PAGE = "/kopare/ta-bort";
const TOKEN = "17." + "x".repeat(22); // shaped like a link token, built so no scanner flags it

// Strict Mode, as the App Router runs in development: every effect runs twice.
function open(hash: string) {
  window.history.replaceState(null, "", PAGE + hash);
  render(
    <StrictMode>
      <EraseBuyer />
    </StrictMode>,
  );
}

const button = () =>
  screen.getByRole("button", { name: "Ta bort mina uppgifter" });

beforeEach(() => eraseBuyerMock.mockReset());
afterEach(cleanup);

describe("takeToken", () => {
  it("reads the fragment and drops it from the address", () => {
    const replaceState = vi.fn();
    const token = takeToken(
      { hash: `#${TOKEN}`, pathname: PAGE } as Location,
      { replaceState } as unknown as History,
    );
    expect(token).toBe(TOKEN);
    expect(replaceState).toHaveBeenCalledWith(null, "", PAGE);
  });

  it("is null without a fragment and leaves the address alone", () => {
    const replaceState = vi.fn();
    const token = takeToken(
      { hash: "", pathname: PAGE } as Location,
      { replaceState } as unknown as History,
    );
    expect(token).toBeNull();
    expect(replaceState).not.toHaveBeenCalled();
  });
});

describe("EraseBuyer", () => {
  it("says what goes, erases nothing on opening, and hides the token", () => {
    open(`#${TOKEN}`);
    expect(
      screen.getByText(/ditt namn, din ort och dina kontaktuppgifter/),
    ).toBeInTheDocument();
    expect(button()).toBeEnabled();
    expect(eraseBuyerMock).not.toHaveBeenCalled();
    expect(window.location.hash).toBe("");
    expect(window.location.href).not.toContain(TOKEN);
  });

  it.each([
    ["removed", "Dina uppgifter är borttagna."],
    ["already_removed", "Dina uppgifter är redan borttagna."],
    [
      "invalid",
      "Länken gäller inte längre. Skriv till dataskydd@gotlandskaninen.se.",
    ],
  ])("posts the token on the button and shows %s", async (result, text) => {
    eraseBuyerMock.mockResolvedValue(result);
    open(`#${TOKEN}`);
    fireEvent.click(button());
    expect(await screen.findByText(text)).toBeInTheDocument();
    expect(eraseBuyerMock).toHaveBeenCalledWith(TOKEN);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("without a token says the link is no longer valid, asking no server", async () => {
    open("");
    fireEvent.click(button());
    expect(
      await screen.findByText(/Länken gäller inte längre/),
    ).toBeInTheDocument();
    expect(eraseBuyerMock).not.toHaveBeenCalled();
  });

  it("keeps the button after an error", async () => {
    eraseBuyerMock.mockResolvedValue("error");
    open(`#${TOKEN}`);
    fireEvent.click(button());
    expect(
      await screen.findByText("Något gick fel. Försök igen om en stund."),
    ).toBeInTheDocument();
    await waitFor(() => expect(button()).toBeEnabled());
  });
});
