import { afterEach, describe, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import { NextSteps } from "@/components/public/NextSteps";

afterEach(cleanup);

describe("NextSteps", () => {
  it("ends a breed page with a way to join and its breed standard", () => {
    render(<NextSteps slug="gotlandskanin" />);
    const block = screen.getByRole("complementary", { name: "Nästa steg" });
    expect(block).toBeTruthy();
    expect(
      screen.getByRole("link", { name: /Bli medlem/ }).getAttribute("href"),
    ).toBe("/bli-medlem");
    expect(
      screen
        .getByRole("link", { name: /Rasram för gotlandskanin/ })
        .getAttribute("href"),
    ).toBe("/rasram-gotlandskanin");
  });

  it("renders nothing for a page without next steps", () => {
    for (const slug of ["okand-sida", "constructor", "toString"]) {
      const { container } = render(<NextSteps slug={slug} />);
      expect(container.firstChild).toBeNull();
    }
  });
});
