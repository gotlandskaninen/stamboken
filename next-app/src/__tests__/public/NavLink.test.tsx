import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { NavLink } from "@/components/public/NavLink.client";
import { NavDropdown } from "@/components/public/NavDropdown.client";

vi.mock("next/navigation", () => ({ usePathname: () => "/historik" }));

afterEach(cleanup);

describe("current page in the menu", () => {
  it("marks only the link matching the path", () => {
    render(
      <>
        <NavLink href="/historik" label="Historik" />
        <NavLink href="/foreningen" label="Föreningen" />
      </>,
    );
    expect(
      screen
        .getByRole("link", { name: "Historik" })
        .getAttribute("aria-current"),
    ).toBe("page");
    expect(
      screen
        .getByRole("link", { name: "Föreningen" })
        .getAttribute("aria-current"),
    ).toBeNull();
  });

  it("styles the dropdown as active when an item is the current page", () => {
    const items = [{ label: "Historik", href: "/historik" }];
    const { rerender } = render(
      <NavDropdown label="Lantras" href="/lantras" items={items} />,
    );
    const weight = () =>
      getComputedStyle(screen.getByRole("button", { name: /Lantras/ }))
        .fontWeight;
    expect(weight()).toBe("600");
    rerender(
      <NavDropdown
        label="Lantras"
        href="/lantras"
        items={[{ label: "X", href: "/x" }]}
      />,
    );
    expect(weight()).toBe("400");
  });
});
