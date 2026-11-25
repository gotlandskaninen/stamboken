import { describe, expect, it } from "vitest";
import {
  kontrollera,
  fragorIOrdning,
  vandra,
  type Nyckel,
} from "@/lib/fargatlas/nyckel";
import { TESTNYCKEL } from "./testnyckel";

const kopia = (): Nyckel => structuredClone(TESTNYCKEL);

describe("nyckeln som data", () => {
  it("vandra stannar vid frågan eller ger numret och anteckningen", () => {
    expect(vandra([], TESTNYCKEL)).toEqual({ fraga: "q1" });
    expect(vandra(["q1-nej"], TESTNYCKEL)).toEqual({ fraga: "q3" });
    expect(vandra(["q1-nej", "q3-ja"], TESTNYCKEL)).toEqual({ nummer: 22 });
    expect(vandra(["q1-ja", "q2-b"], TESTNYCKEL)).toEqual({
      nummer: 99,
      anteckning: "Testanteckning.",
    });
  });

  it("vandra vägrar ett svar som inte hör till frågan eller kommer efter numret", () => {
    expect(() => vandra(["q1-nej", "q2-a"], TESTNYCKEL)).toThrow();
    expect(() => vandra(["q1-nej", "q3-ja", "q1-ja"], TESTNYCKEL)).toThrow();
  });

  it("frågorna numreras med starten först och i den ordning människor numrerar dem", () => {
    // the API sorts the keys of the object, so q10 can come before q2
    const fragor = {
      q10: TESTNYCKEL.fragor.q3,
      q2: TESTNYCKEL.fragor.q2,
      q1: TESTNYCKEL.fragor.q1,
      q9b: TESTNYCKEL.fragor.q3,
    };
    expect(fragorIOrdning({ ...TESTNYCKEL, fragor })).toEqual([
      "q1",
      "q2",
      "q9b",
      "q10",
    ]);
  });

  it("kontrollera godtar en hel nyckel", () => {
    expect(kontrollera(TESTNYCKEL)).toBeNull();
  });

  it("kontrollera hittar en slinga, en död hänvisning, en tom fråga och en saknad start", () => {
    const slinga = kopia();
    slinga.fragor.q3.svar[0].till = "q1";
    expect(kontrollera(slinga)).toMatch(/tillbaka till q1/);

    const dod = kopia();
    dod.fragor.q2.svar[0].till = "q9";
    expect(kontrollera(dod)).toMatch(/q9, som inte finns/);

    const tom = kopia();
    tom.fragor.q2.svar = [];
    expect(kontrollera(tom)).toMatch(/q2 saknar svar/);

    expect(kontrollera({ ...kopia(), start: "q0" })).toMatch(/första fråga/);
    expect(kontrollera(null)).not.toBeNull();
  });

  it("kontrollera kastar aldrig, också för en nyckel av fel form", () => {
    const utanMal = kopia();
    (utanMal.fragor.q1.svar[0] as unknown as { till: null }).till = null;
    expect(kontrollera(utanMal)).toMatch(/leder ingenstans/);

    const tomtSvar = kopia();
    (tomtSvar.fragor.q1.svar as unknown[])[0] = null;
    expect(kontrollera(tomtSvar)).toMatch(/fel form/);

    expect(kontrollera({ ...kopia(), efter_numret: {} as never })).toMatch(
      /efter numret/,
    );
    expect(kontrollera({ ...kopia(), fragor: null as never })).toMatch(
      /saknar frågor/,
    );
  });

  it("kontrollera vägrar två svar med samma id och ärvda namn som frågor", () => {
    const dubbel = kopia();
    dubbel.fragor.q3.svar[1].id = "q3-ja"; // leads to 11, but the guide would follow the first q3-ja to 22
    expect(kontrollera(dubbel)).toMatch(/två svar med id q3-ja/);

    const arvd = kopia();
    arvd.fragor.q1.svar[0].till = "constructor";
    expect(kontrollera(arvd)).toMatch(/constructor, som inte finns/);
    expect(kontrollera({ ...kopia(), start: "toString" })).toMatch(
      /första fråga/,
    );
    const [rex] = TESTNYCKEL.efter_numret!;
    expect(
      kontrollera({ ...kopia(), efter_numret: [rex, { ...rex }] }),
    ).toMatch(/samma id/);
  });
});
