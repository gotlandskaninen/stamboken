import React from "react";
import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup } from "@testing-library/react";
import { UserProvider, type UserContext } from "@/lib/user-context";
import { CheckPageNameHint } from "@/components/herd/CheckPageNameHint";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const user = (choice: boolean | null) =>
  ({
    id: 1,
    email: "a@example.org",
    name_on_check_page: choice,
  }) as UserContext;

describe("CheckPageNameHint (stamboken #6)", () => {
  afterEach(cleanup);

  it("asks a person who has not chosen, with a link to Min profil", () => {
    const { container } = render(
      <UserProvider user={user(null)}>
        <CheckPageNameHint />
      </UserProvider>,
    );
    expect(container.textContent).toContain("addRabbit.checkPageNameHint");
    expect(screen.getByRole("link").getAttribute("href")).toBe(
      "/stamboken/profil",
    );
  });

  it.each([true, false])("stays away once she has chosen (%s)", (choice) => {
    const { container } = render(
      <UserProvider user={user(choice)}>
        <CheckPageNameHint />
      </UserProvider>,
    );
    expect(container.textContent).toBe("");
  });

  it("stays away without a signed-in user", () => {
    const { container } = render(<CheckPageNameHint />);
    expect(container.textContent).toBe("");
  });
});
