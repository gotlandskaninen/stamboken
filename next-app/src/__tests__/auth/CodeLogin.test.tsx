import "@testing-library/jest-dom/vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
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
  await waitFor(() =>
    expect(actions.redeemLoginLink).toHaveBeenLastCalledWith("test-token", 12),
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
    <CreateAccount version="23">
      <p>Hela regeltexten</p>
    </CreateAccount>,
  );
  expect(screen.getByText("Hela regeltexten")).toBeVisible();
  expect(screen.getByRole("link", { name: /personuppgifter/ })).toHaveAttribute(
    "href",
    "/dataskydd",
  );
  const submit = screen.getByRole("button", { name: "Skapa mitt konto" });
  expect(submit).toBeDisabled();
  fireEvent.click(
    screen.getByRole("checkbox", {
      name: "Jag har läst reglerna och följer dem.",
    }),
  );
  fireEvent.click(submit);
  await screen.findByText(/Ditt konto kopieras dit i natt/);
  expect(actions.createMemberAccount).toHaveBeenCalledWith(
    true,
    "23",
    undefined,
  );
});
it("explains a missing publication and provides no creation button", () => {
  render(<CreateAccount />);
  expect(screen.getByRole("alert")).toHaveTextContent(
    "Reglerna går inte att hämta",
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
});
