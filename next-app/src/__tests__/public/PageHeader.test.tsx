import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { PageHeader } from "@/components/public/PageHeader";

afterEach(cleanup);

describe("PageHeader breadcrumb", () => {
  it("shows the parent link between Hem and the section", () => {
    render(
      <PageHeader
        section="Rasram"
        title="Rasram"
        parent={{ label: "Gotlandskanin", href: "/gotlandskanin" }}
      />,
    );
    expect(
      screen.getByRole("link", { name: "Gotlandskanin" }).getAttribute("href"),
    ).toBe("/gotlandskanin");
    expect(screen.getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Hem",
      "Gotlandskanin",
    ]);
  });

  it("has only Hem as a link without a parent", () => {
    render(<PageHeader section="Rasram" title="Rasram" />);
    expect(screen.getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Hem",
    ]);
  });
});

describe("PageHeader action", () => {
  it("renders the page's one action as a button link under the lede", () => {
    render(
      <PageHeader
        section="Bli medlem"
        title="Bli medlem"
        lede="Medlemskapet kostar 200 kr om året."
        action={{ label: "Ansök om medlemskap", href: "/ansok" }}
      />,
    );
    expect(
      screen
        .getByRole("link", { name: "Ansök om medlemskap" })
        .getAttribute("href"),
    ).toBe("/ansok");
  });
});
