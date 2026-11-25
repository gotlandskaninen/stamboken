import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  CodeLoginForm,
  LoginLink,
  CreateAccount,
} from "@/components/auth/CodeLogin";
import * as actions from "@/app/(app)/(auth)/actions";

vi.mock("@/app/(app)/(auth)/actions", () => ({
  requestLoginCode: vi.fn(),
  verifyLoginCode: vi.fn(),
  lookupLoginLink: vi.fn(),
  redeemLoginLink: vi.fn(),
  createMemberAccount: vi.fn(),
}));
beforeEach(() => {
  vi.resetAllMocks();
  history.replaceState(null, "", "/");
});
afterEach(cleanup);

it("shows the same delivery message and accepts grouped digits on a phone", async () => {
  vi.mocked(actions.requestLoginCode).mockResolvedValue(true);
  vi.mocked(actions.verifyLoginCode).mockResolvedValue({
    error: "invalidCode",
  });
  render(<CodeLoginForm />);
  fireEvent.change(screen.getByLabelText("E-postadress i matrikeln"), {
    target: { value: "member@example.org" },
  });
  fireEvent.click(screen.getByRole("button", { name: "Skicka kod" }));
  const code = await screen.findByLabelText("Engångskod");
  expect(screen.getByRole("status")).toHaveTextContent("inom en minut");
  expect(code).toHaveAttribute("inputmode", "numeric");
  expect(code).toHaveAttribute("autocomplete", "one-time-code");
  fireEvent.change(code, { target: { value: "0123 - 4567" } });
  fireEvent.click(screen.getByRole("button", { name: "Logga in med kod" }));
  await screen.findByRole("alert");
  expect(actions.verifyLoginCode).toHaveBeenCalledWith(
    "01234567",
    undefined,
    undefined,
  );
});

it("removes the fragment from the same history entry, shows the name, then requests a switch on conflict", async () => {
  history.replaceState({ marker: 1 }, "", "/auth/kod#test-token");
  const length = history.length;
  vi.mocked(actions.lookupLoginLink).mockResolvedValue({
    name: "Testmedlem",
    switchFrom: null,
  });
  vi.mocked(actions.redeemLoginLink)
    .mockResolvedValueOnce({ switchFrom: 12 })
    .mockResolvedValueOnce({ error: "invalidLink" });
  render(<LoginLink enabled />);
  await screen.findByText("Du är på väg att logga in som Testmedlem.");
  expect(location.hash).toBe("");
  expect(JSON.stringify(history.state)).not.toContain("test-token");
  expect(history.length).toBe(length);
  expect(actions.redeemLoginLink).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Logga in här" }));
  const confirm = await screen.findByRole("button", {
    name: "Byt konto och logga in",
  });
  expect(actions.redeemLoginLink).toHaveBeenLastCalledWith(
    "test-token",
    undefined,
  );
  fireEvent.click(confirm);
  await waitFor(
    () =>
      expect(actions.redeemLoginLink).toHaveBeenLastCalledWith(
        "test-token",
        12,
      ),
    { timeout: 3000 }, // the default 1 s was too short when the whole suite runs
  );
});

it("shows the browser requirement without a name or button when lookup fails", async () => {
  history.replaceState(null, "", "/auth/kod#test-token");
  vi.mocked(actions.lookupLoginLink).mockResolvedValue(null);
  render(<LoginLink enabled />);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "webbläsaren där du bad om koden",
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
it("removes the fragment even when code login is disabled", () => {
  history.replaceState(null, "", "/auth/kod#test-token");
  render(<LoginLink enabled={false} />);
  expect(location.hash).toBe("");
  expect(actions.lookupLoginLink).not.toHaveBeenCalled();
});
it("shows the full rules and requires an explicit agreement to the displayed version", async () => {
  vi.mocked(actions.createMemberAccount).mockResolvedValue({
    demoAccountCreated: true,
  });
  render(
    <CreateAccount rules={{ version: "23", sha256: "a".repeat(64) }}>
      <p>Hela regeltexten</p>
    </CreateAccount>,
  );
  expect(screen.getByText("Hela regeltexten")).toBeVisible();
  expect(screen.getByText(/kryssa sedan i rutan under dem/)).toBeVisible();
  expect(screen.getByText(/e-postadress är bekräftad/)).toBeVisible();
  expect(
    screen.getByRole("link", { name: "Hoppa till rutan" }),
  ).toHaveAttribute("href", "#godkann");
  expect(
    screen.getByRole("link", { name: "Regler för ditt konto" }),
  ).toHaveAttribute("href", "/kontoregler");
  const privacyLink = screen.getByRole("link", { name: "Integritetspolicyn" });
  expect(privacyLink).toHaveAttribute("href", "/dataskydd");
  expect(privacyLink.closest("p")).toHaveTextContent(
    "Så behandlar föreningen dina uppgifter: Integritetspolicyn",
  );
  expect(privacyLink.closest("label")).toBeNull();
  const checkbox = screen.getByRole("checkbox", {
    name: "Jag har läst reglerna och följer dem.",
  });
  expect(checkbox).not.toBeChecked();
  const submit = screen.getByRole("button", { name: "Skapa mitt konto" });
  // A press without the tick explains itself and leads to the box.
  fireEvent.click(submit);
  expect(screen.getByRole("alert")).toHaveTextContent("Kryssa först i rutan");
  expect(checkbox).toHaveFocus();
  expect(checkbox).toHaveAttribute("aria-describedby", "godkann-fel");
  expect(actions.createMemberAccount).not.toHaveBeenCalled();
  fireEvent.click(checkbox);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  fireEvent.click(submit);
  await screen.findByText(/Ditt konto kopieras dit i natt/);
  expect(actions.createMemberAccount).toHaveBeenCalledWith(
    true,
    { version: "23", sha256: "a".repeat(64) },
    undefined,
  );
});
it("clears the agreement when updated rules arrive after submission", async () => {
  vi.mocked(actions.createMemberAccount).mockResolvedValue({
    error: "rulesChanged",
  });
  const form = (text: string, sha256: string) => (
    <CreateAccount rules={{ version: "23", sha256 }}>{text}</CreateAccount>
  );
  const { rerender } = render(form("Första texten", "a".repeat(64)));
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Skapa mitt konto" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Reglerna har uppdaterats",
  );
  expect(screen.getByRole("link", { name: "Läs reglerna" })).toHaveAttribute(
    "href",
    "#kontoregler",
  );
  rerender(form("Nya regler", "b".repeat(64)));
  expect(screen.getByText("Nya regler")).toBeVisible();
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  fireEvent.click(screen.getByRole("button", { name: "Skapa mitt konto" }));
  expect(screen.getByRole("alert")).toHaveTextContent("Kryssa först i rutan");
  expect(actions.createMemberAccount).toHaveBeenCalledTimes(1);
});
it.each([
  ["expired" as const, "Begär en ny kod", "/auth/sign-in"],
  ["accountConflict" as const, "Till inloggningen", "/auth/sign-in"],
])("gives the %s error a way on", async (error, name, href) => {
  vi.mocked(actions.createMemberAccount).mockResolvedValue({ error });
  render(<CreateAccount rules={{ version: "23", sha256: "a".repeat(64) }} />);
  fireEvent.click(screen.getByRole("checkbox"));
  fireEvent.click(screen.getByRole("button", { name: "Skapa mitt konto" }));
  const alert = await screen.findByRole("alert");
  expect(within(alert).getByRole("link", { name })).toHaveAttribute(
    "href",
    href,
  );
});
it("explains a missing publication and provides no creation button", () => {
  render(<CreateAccount />);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Reglerna går inte att hämta",
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
