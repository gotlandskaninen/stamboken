import { describe, it, expect, afterEach, vi } from "vitest";
import { render, screen, cleanup, fireEvent } from "@testing-library/react";
import { FargNyckel } from "@/components/fargatlas/FargNyckel";
import { NyckelLista } from "@/components/fargatlas/NyckelLista";
import type { AtlasFarg } from "@/lib/fargatlas/atlas";
import { TESTNYCKEL } from "./testnyckel";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
  }: {
    href: string;
    children: React.ReactNode;
  }) => <a href={href}>{children}</a>,
}));

afterEach(cleanup);

// Made-up texts and key: no atlas text, photo or key goes in the repo.
const viltgra: AtlasFarg = {
  id: 22,
  name: "Viltgrå",
  comment: null,
  genebank: "Gotlandskanin",
  beskrivning: "Testbeskrivning",
  skiljs_fran: null,
  foton: [],
};
// The atlas's colours come from the database; these are the numbers the made-up key reaches in the tests.
const allt: AtlasFarg = {
  ...viltgra,
  id: 99,
  name: "Testfärg",
  beskrivning: null,
};
const svart: AtlasFarg = {
  ...viltgra,
  id: 11,
  name: "Svart",
  beskrivning: null,
};
const data = {
  fotoBas: "/api",
  atlas: {
    version: "test",
    grupper: {},
    farger: [viltgra, allt, svart],
    nyckel: TESTNYCKEL,
  },
};

const svara = (text: string) =>
  fireEvent.click(
    screen.getByRole("button", {
      name: (namn: string) => namn.startsWith(text),
    }),
  );
const tillViltgra = () => ["Nej", "Ja, testvilt"].forEach(svara);

describe("FargNyckel", () => {
  it("vägen till 22 ger resultatet och onValj(22)", () => {
    const onValj = vi.fn();
    render(<FargNyckel data={data} onValj={onValj} />);
    tillViltgra();
    expect(screen.getByRole("heading", { name: "22 Viltgrå" })).toBeDefined();
    expect(screen.getByText("Testbeskrivning")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Välj 22 Viltgrå" }));
    expect(onValj).toHaveBeenCalledWith(22, []);
  });

  it("Ja på frågan om pälsen visar påminnelsen och följer med Välj", () => {
    const onValj = vi.fn();
    render(<FargNyckel data={data} onValj={onValj} />);
    tillViltgra();
    expect(
      screen.getByRole("group", { name: "Testfråga om pälsen?" }),
    ).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Ja" }));
    expect(screen.getByText("Testsvar: välj Rex vid Päls.")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Välj 22 Viltgrå" }));
    expect(onValj).toHaveBeenCalledWith(22, ["Testsvar: välj Rex vid Päls."]);
  });

  it("färganteckningen följer med Välj som påminnelse", () => {
    const onValj = vi.fn();
    render(<FargNyckel data={data} onValj={onValj} />);
    svara("Ja");
    svara("Testsvar B");
    fireEvent.click(screen.getByRole("button", { name: /^Välj 99/ }));
    expect(onValj).toHaveBeenCalledWith(99, [
      "Färganteckning: Testanteckning.",
    ]);
  });

  it("resultatets foto visar bildtext och fotograf", () => {
    const medFoto = {
      ...data,
      atlas: {
        ...data.atlas,
        farger: [
          {
            ...viltgra,
            foton: [
              { id: "22-a", fotograf: "Test Fotograf", bildtext: "Testbild" },
            ],
          },
        ],
      },
    };
    render(<FargNyckel data={medFoto} />);
    tillViltgra();
    expect(screen.getByText("Testbild · Foto: Test Fotograf")).toBeDefined();
  });

  it("ett nummer som saknas i färglistan säger det i stället för att ge ett råd", () => {
    const utan22 = { ...data, atlas: { ...data.atlas, farger: [] } };
    const onValj = vi.fn();
    render(<FargNyckel data={utan22} onValj={onValj} />);
    tillViltgra();
    expect(screen.getByRole("alert").textContent).toMatch(
      /22 finns inte i Stambokens färglista/,
    );
    expect(screen.queryByRole("button", { name: /^Välj/ })).toBeNull();
  });

  it("Tillbaka går ett steg och fokus följer med till frågan", () => {
    render(<FargNyckel data={data} />);
    expect(screen.queryByRole("button", { name: "Tillbaka" })).toBeNull();
    svara("Nej");
    expect(screen.getByRole("heading", { level: 3 }).textContent).toBe(
      "Testfråga tre?",
    );
    fireEvent.click(screen.getByRole("button", { name: "Tillbaka" }));
    const forsta = screen.getByRole("heading", { level: 3 });
    expect(forsta.textContent).toBe("Testfråga ett?");
    expect(document.activeElement).toBe(forsta);
  });

  it("spåret visar svaren och går tillbaka till en tidigare fråga", () => {
    render(<FargNyckel data={data} />);
    tillViltgra();
    const spar = screen.getByRole("list", { name: "Dina svar" });
    expect(spar.textContent).toBe("NejJa, testvilt");
    fireEvent.click(screen.getByRole("button", { name: /^Ändra fråga 1/ }));
    expect(screen.getByRole("heading", { level: 3 }).textContent).toBe(
      "Testfråga ett?",
    );
  });

  it("Börja om går till första frågan", () => {
    render(<FargNyckel data={data} />);
    tillViltgra();
    fireEvent.click(screen.getByRole("button", { name: "Börja om" }));
    expect(screen.getByRole("heading", { level: 3 }).textContent).toBe(
      "Testfråga ett?",
    );
    expect(screen.queryByRole("list", { name: "Dina svar" })).toBeNull();
  });

  it("anteckningen och hjälptexterna visas", () => {
    render(<FargNyckel data={data} />);
    expect(screen.getByText("Testhjälp ett.")).toBeDefined();
    svara("Ja");
    expect(screen.getByText("Testhjälp A.")).toBeDefined();
    svara("Testsvar B");
    expect(screen.getByText("Testanteckning.")).toBeDefined();
  });

  it("på sidan säger resultatet var numret används, i stället för Välj", () => {
    render(<FargNyckel data={data} />);
    tillViltgra();
    expect(screen.queryByRole("button", { name: /^Välj/ })).toBeNull();
    expect(
      screen.getByRole("link", { name: "Min besättning" }).getAttribute("href"),
    ).toBe("/stamboken/min-besattning");
  });

  it("meddelandet om en saknad färg gäller bara det numret", () => {
    render(<FargNyckel data={data} onValj={() => {}} saknas={22} />);
    tillViltgra();
    expect(screen.getByText(/Färg 22 finns inte i färglistan/)).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Tillbaka" }));
    svara("Nej, testsvart");
    expect(screen.queryByText(/finns inte i färglistan/)).toBeNull();
  });

  it("guiden börjar om när en annan nyckel kommer mitt i", () => {
    const { rerender } = render(<FargNyckel data={data} />);
    svara("Nej");
    expect(screen.getByText("Testfråga tre?")).toBeDefined();
    const annan = structuredClone(TESTNYCKEL);
    annan.fragor.q1.svar[1].id = "q1-annat"; // the old answer id is not in the new key
    rerender(
      <FargNyckel
        data={{ ...data, atlas: { ...data.atlas, nyckel: annan } }}
      />,
    );
    expect(screen.getByText("Testfråga ett?")).toBeDefined();
    expect(screen.queryByRole("list", { name: "Dina svar" })).toBeNull();
  });

  it("en nyckel med en slinga eller utan nyckel stoppas med ett meddelande", () => {
    const slinga = structuredClone(TESTNYCKEL);
    slinga.fragor.q3.svar[0].till = "q1";
    const { rerender } = render(
      <FargNyckel
        data={{ ...data, atlas: { ...data.atlas, nyckel: slinga } }}
      />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(
      /går inte att använda/,
    );
    rerender(
      <FargNyckel data={{ ...data, atlas: { ...data.atlas, nyckel: null } }} />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(
      /går inte att använda/,
    );
    rerender(<FargNyckel data={undefined} />);
    expect(screen.getByText("Hämtar nyckeln …")).toBeDefined();
  });
});

describe("NyckelLista", () => {
  it("numrerar frågorna och visar vart varje svar leder", () => {
    render(<NyckelLista nyckel={TESTNYCKEL} farger={[viltgra]} />);
    expect(
      screen.getByRole("heading", {
        name: "Bestämningsnyckeln för gotlandskanin",
        hidden: true,
      }),
    ).toBeDefined();
    expect(screen.getByText(/Ja, testvilt → 22 Viltgrå/)).toBeDefined();
    expect(screen.getByText(/^Nej → fråga 3/)).toBeDefined();
    // 12 is not in this colour list: the printed key says so, as the guide on screen does
    expect(
      screen.getByText(
        /Testsvar A \(Testhjälp A\.\) → 12, som inte finns i Stambokens färglista/,
      ),
    ).toBeDefined();
  });
});
