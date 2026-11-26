import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { Hopplista } from "@/components/fargatlas/Hopplista";
import type { AtlasFarg } from "@/lib/fargatlas/atlas";

afterEach(() => {
  cleanup();
  location.hash = "";
});

const farg = (id: number, name: string): AtlasFarg => ({
  id,
  name,
  comment: null,
  genebank: "Gotlandskanin",
  beskrivning: null,
  skiljs_fran: null,
  foton: [],
});

describe("Hopplista", () => {
  it("länkar till grupperna och hoppar till ett nummer först när man trycker Visa", () => {
    render(
      <Hopplista
        grupper={[{ id: "testgrupp", namn: "Testgrupp", nummer: [11, 22] }]}
        farger={[farg(11, "Svart"), farg(22, "Viltgrå")]}
      />,
    );
    expect(
      screen.getByRole("link", { name: "Testgrupp" }).getAttribute("href"),
    ).toBe("#grupp-testgrupp");
    fireEvent.change(screen.getByLabelText("Gå till nummer"), {
      target: { value: "22" },
    });
    expect(location.hash).toBe(""); // choosing alone does not move the page
    fireEvent.click(screen.getByRole("button", { name: "Visa" }));
    expect(location.hash).toBe("#farg-22");
  });
});
