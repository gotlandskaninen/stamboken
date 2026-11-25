import { describe, it, expect } from "vitest";
import { translateReason, translateReasons } from "@/utils/translateReasons";

const NBSP = "\u00a0";

describe("translateReason", () => {
  it("names the founderdjur of a sole carrier", () => {
    expect(
      translateReason("Sole active carrier of founder G1-1101", "G2-2301"),
    ).toBe("Enda kaninen i beräkningen med gener från founderdjuret G1-1101");
  });

  it("says when the founderdjur is the rabbit itself", () => {
    expect(
      translateReason("Sole active carrier of founder G1-1101", "G1-1101"),
    ).toBe("Är själv founderdjur och har inga ättlingar i beräkningen");
    expect(
      translateReason("Carries underrepresented founder G1-1101", "G1-1101"),
    ).toBe("Är själv founderdjur, med liten andel av generna i beräkningen");
  });

  it("says 'på eller under' with Swedish percentages, as the backend tests <=", () => {
    expect(
      translateReason("Mean kinship 0.0023 is below 5th percentile (0.0023)"),
    ).toBe(
      `Medelsläktskap 0,23${NBSP}%, på eller under gränsen för de 5${NBSP}% minst släkta (0,23${NBSP}%)`,
    );
    expect(
      translateReason("Mean kinship 0.0110 is below 25th percentile (0.0120)"),
    ).toBe(
      `Medelsläktskap 1,10${NBSP}%, på eller under gränsen för de 25${NBSP}% minst släkta (1,20${NBSP}%)`,
    );
  });

  it("translates genome uniqueness and the underrepresented founderdjur", () => {
    expect(
      translateReason(
        "Genome uniqueness 0.1030 is above 75th percentile (0.0800)",
      ),
    ).toBe(
      `Unika gener 10,3${NBSP}%, över gränsen för de 25${NBSP}% med flest unika gener (8,0${NBSP}%)`,
    );
    expect(translateReason("Carries underrepresented founder G1-1101")).toBe(
      "Bär gener från founderdjuret G1-1101, som har liten andel av generna i beräkningen",
    );
  });

  it("leaves the breeding reasons and unknown text as they were", () => {
    expect(translateReason("Sire MK=0.0100, Dam MK=0.0200")).toBe(
      "Hane MK=0.0100, Hona MK=0.0200",
    );
    expect(translateReason("Something new")).toBe("Something new");
  });
});

describe("translateReasons", () => {
  it("passes the rabbit's number to every reason, not the list index", () => {
    expect(
      translateReasons(
        [
          "Genetic representation within normal range",
          "Sole active carrier of founder 1",
        ],
        "G2-2301",
      ),
    ).toEqual([
      "–",
      "Enda kaninen i beräkningen med gener från founderdjuret 1",
    ]);
  });
});
