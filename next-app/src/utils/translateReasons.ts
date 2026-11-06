/**
 * Translates English reason strings from the genetics backend to Swedish.
 *
 * The backend returns reason strings in English (see genetics.py).
 * Rather than modifying the API contract, we translate on the frontend.
 */

const patterns: [RegExp, string][] = [
  // Genetic priorities (genetics.py calculate_genetic_priorities)
  [/^Sole active carrier of founder (.+)$/, "Enda aktiva bärare av founder $1"],
  [
    /^Mean kinship ([\d.]+) is below 5th percentile \(([\d.]+)\)$/,
    "Medelkinship $1 är under 5:e percentilen ($2)",
  ],
  [
    /^Mean kinship ([\d.]+) is below 25th percentile \(([\d.]+)\)$/,
    "Medelkinship $1 är under 25:e percentilen ($2)",
  ],
  [
    /^Genome uniqueness ([\d.]+) is above 75th percentile \(([\d.]+)\)$/,
    "Genomunikhet $1 är över 75:e percentilen ($2)",
  ],
  [
    /^Carries underrepresented founder (.+)$/,
    "Bär underrepresenterad founder $1",
  ],
  [
    /^Genetic representation within normal range$/,
    "Genetisk representation inom normalintervall",
  ],

  // Breeding suggestions (genetics.py suggest_breeding_pairs)
  [/^Sire MK=([\d.]+), Dam MK=([\d.]+)$/, "Hane MK=$1, Hona MK=$2"],
  [/^Parents are unrelated$/, "Föräldrarna är obesläktade"],
  [/^Low offspring inbreeding$/, "Låg inavel hos avkomma"],
];

export function translateReason(reason: string): string {
  for (const [pattern, replacement] of patterns) {
    if (pattern.test(reason)) {
      return reason.replace(pattern, replacement);
    }
  }
  return reason; // fallback: show original English
}

export function translateReasons(reasons: string[]): string[] {
  return reasons.map(translateReason);
}
