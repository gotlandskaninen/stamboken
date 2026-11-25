import React from "react";
import { describe, it, expect, afterEach } from "vitest";
import { render, screen, cleanup, within } from "@testing-library/react";
import { FargKort } from "@/components/fargatlas/FargKort";
import { FargatlasVy } from "@/components/fargatlas/FargatlasVy";
import type { AtlasFarg, AtlasNyckel } from "@/lib/fargatlas/atlas";

afterEach(cleanup);

// Made-up texts; the real atlas texts and photos never go in the repo.
const viltgra: AtlasFarg = {
  id: 22,
  name: "Viltgrå",
  comment: "Testkommentar",
  genebank: "Gotlandskanin",
  beskrivning: "Testbeskrivning",
  skiljs_fran: "Testskillnad",
  foton: [{ id: "22-a", fotograf: "Test Fotograf", bildtext: "Testbild" }],
};
const utanFoto: AtlasFarg = {
  id: 24,
  name: "Rödgul",
  comment: null,
  genebank: "Gotlandskanin",
  beskrivning: null,
  skiljs_fran: null,
  foton: [],
};

describe("FargKort", () => {
  it('visar nummer, namn, beskrivning och "skiljs från"', () => {
    render(<FargKort farg={viltgra} fotoBas="/api" />);
    expect(screen.getByRole("heading", { name: "22 Viltgrå" })).toBeDefined();
    expect(screen.getByText("Testkommentar")).toBeDefined();
    expect(screen.getByText("Testbeskrivning")).toBeDefined();
    expect(screen.getByText("Testskillnad")).toBeDefined();
    expect(screen.getByText(/Skiljs från/)).toBeDefined();
    const img = screen.getByRole("img") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe(
      "/api/v2/fargatlas/foto/22-a?storlek=480",
    );
    expect(img.getAttribute("loading")).toBe("lazy");
    expect(
      screen
        .getByRole("link", { name: "22 Viltgrå, större bild i ny flik" })
        .getAttribute("href"),
    ).toBe("/api/v2/fargatlas/foto/22-a?storlek=1600");
  });

  it("utan foto har kortet ingen bildyta", () => {
    render(<FargKort farg={utanFoto} fotoBas="/api" />);
    expect(screen.queryByText("Foto saknas")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.queryByText(/Skiljs från/)).toBeNull();
  });

  it("fotograf visas bara när den finns", () => {
    const { rerender } = render(<FargKort farg={viltgra} fotoBas="/api" />);
    expect(screen.getByText(/Foto: Test Fotograf/)).toBeDefined();
    rerender(
      <FargKort
        farg={{ ...viltgra, foton: [{ ...viltgra.foton[0], fotograf: null }] }}
        fotoBas="/api"
      />,
    );
    expect(screen.queryByText(/Foto:/)).toBeNull();
  });

  it("hämtar fotot från testmiljöns API i testläget", () => {
    render(<FargKort farg={viltgra} fotoBas="/api-test" />);
    expect(screen.getByRole("img").getAttribute("src")).toBe(
      "/api-test/v2/fargatlas/foto/22-a?storlek=480",
    );
  });
});

// A made-up key: the real one comes from the atlas package and is checked in the operations repo.
const nyckel: AtlasNyckel = {
  start: "q1",
  fragor: {},
  grupper: [
    { id: "testvilt", namn: "Testgrupp vilt", nummer: [22, 24] },
    { id: "testmellerud", namn: "Testgrupp mellerud", nummer: [101] },
  ],
};
const albino: AtlasFarg = {
  ...utanFoto,
  id: 101,
  name: "Albino",
  genebank: "Mellerudskanin",
};

describe("FargatlasVy", () => {
  it("grupperar efter nyckelns grupper med gruppens text", () => {
    render(
      <FargatlasVy
        atlas={{
          version: "test",
          grupper: { testvilt: { beskrivning: "Testtext om gruppen" } },
          farger: [viltgra, utanFoto, albino],
          nyckel,
        }}
        fotoBas="/api"
      />,
    );
    const rubriker = screen.getAllByRole("heading", { level: 2 });
    expect(rubriker.map((h) => h.textContent)).toEqual([
      "Testgrupp vilt",
      "Testgrupp mellerud",
    ]);
    expect(screen.getByText("Testtext om gruppen")).toBeDefined();
    const vilt = screen.getByRole("region", { name: "Testgrupp vilt" });
    expect(
      within(vilt).getByRole("heading", { name: "22 Viltgrå" }),
    ).toBeDefined();
    expect(
      within(vilt).getByRole("heading", { name: "24 Rödgul" }),
    ).toBeDefined();
  });

  it("utan nyckel visas färgerna per genbank i nummerordning", () => {
    render(
      <FargatlasVy
        atlas={{
          version: null,
          grupper: {},
          farger: [viltgra, utanFoto, albino],
          nyckel: null,
        }}
        fotoBas="/api"
      />,
    );
    expect(
      screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent),
    ).toEqual(["Gotlandskanin", "Mellerudskanin"]);
    const gotland = screen.getByRole("region", { name: "Gotlandskanin" });
    expect(
      within(gotland)
        .getAllByRole("heading", { level: 3 })
        .map((h) => h.textContent),
    ).toEqual(["22 Viltgrå", "24 Rödgul"]);
  });

  it("en färg utan grupp visas under Övriga färger", () => {
    const ny = { ...utanFoto, id: 102, name: "Testfärg" };
    render(
      <FargatlasVy
        atlas={{ version: null, grupper: {}, farger: [viltgra, ny], nyckel }}
        fotoBas="/api"
      />,
    );
    const ovriga = screen.getByRole("region", { name: "Övriga färger" });
    expect(
      within(ovriga).getByRole("heading", { name: "102 Testfärg" }),
    ).toBeDefined();
  });
});
