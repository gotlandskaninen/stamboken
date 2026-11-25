/**
 * Translates English reason strings from the genetics backend to Swedish.
 *
 * The backend returns reason strings in English (see genetics.py).
 * Rather than modifying the API contract, we translate on the frontend.
 */

import { percent } from "@/lib/genetics";

// A function gets the rabbit's own number first, then the regex groups.
type Replacement =
  | string
  | ((self: string | undefined, ...groups: string[]) => string);

const pct = (value: string, digits: number) => percent(Number(value), digits);

const patterns: [RegExp, Replacement][] = [
  // Genetic priorities (genetics.py calculate_genetic_priorities)
  [
    /^Sole active carrier of founder (.+)$/,
    (self, founder) =>
      founder === self
        ? "Är själv founderdjur och har inga ättlingar i beräkningen"
        : `Enda kaninen i beräkningen med gener från founderdjuret ${founder}`,
  ],
  // The backend tests mk <= the percentile, hence "på eller under".
  [
    /^Mean kinship ([\d.]+) is below 5th percentile \(([\d.]+)\)$/,
    (_, mk, limit) =>
      `Medelsläktskap ${pct(mk, 2)}, på eller under gränsen för de 5\u00a0% minst släkta (${pct(limit, 2)})`,
  ],
  [
    /^Mean kinship ([\d.]+) is below 25th percentile \(([\d.]+)\)$/,
    (_, mk, limit) =>
      `Medelsläktskap ${pct(mk, 2)}, på eller under gränsen för de 25\u00a0% minst släkta (${pct(limit, 2)})`,
  ],
  [
    /^Genome uniqueness ([\d.]+) is above 75th percentile \(([\d.]+)\)$/,
    (_, gu, limit) =>
      `Unika gener ${pct(gu, 1)}, över gränsen för de 25\u00a0% med flest unika gener (${pct(limit, 1)})`,
  ],
  [
    /^Carries underrepresented founder (.+)$/,
    (self, founder) =>
      founder === self
        ? "Är själv founderdjur, med liten andel av generna i beräkningen"
        : `Bär gener från founderdjuret ${founder}, som har liten andel av generna i beräkningen`,
  ],
  [/^Genetic representation within normal range$/, "–"],

  // Breeding suggestions (genetics.py suggest_breeding_pairs)
  [
    /^Sire MK=([\d.]+), Dam MK=([\d.]+)$/,
    (_, sire, dam) => `Hane MK=${pct(sire, 2)}, Hona MK=${pct(dam, 2)}`,
  ],
  [/^Parents are unrelated$/, "Föräldrarna är obesläktade"],
  [/^Low offspring inbreeding$/, "Låg inavel hos avkomma"],
];

/** `self` is the rabbit's individual number, so a founderdjur's own line reads right. */
export function translateReason(reason: string, self?: string): string {
  for (const [pattern, replacement] of patterns) {
    const match = reason.match(pattern);
    if (match) {
      return typeof replacement === "string"
        ? reason.replace(pattern, replacement)
        : replacement(self, ...match.slice(1));
    }
  }
  return reason; // fallback: show original English
}

export function translateReasons(reasons: string[], self?: string): string[] {
  return reasons.map((reason) => translateReason(reason, self));
}
