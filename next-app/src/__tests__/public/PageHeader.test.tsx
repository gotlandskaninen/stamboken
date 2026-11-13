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
