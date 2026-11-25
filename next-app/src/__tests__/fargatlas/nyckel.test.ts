import { describe, expect, it } from "vitest";
import {
  kontrollera,
  nabaraNummer,
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

  it("nabaraNummer ger de nummer någon väg slutar i", () => {
    expect([...nabaraNummer(TESTNYCKEL)].sort((a, b) => a - b)).toEqual([
      11, 12, 22, 99,
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
});
