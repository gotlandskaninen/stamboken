export type Band = "A" | "B" | "C" | "D" | "E";
export type BandReason =
  | "dead"
  | "outside_genebank"
  | "incomplete_pedigree"
  | "small_reference"
  | null;

export interface IndividualGeneticsData {
  inbreeding: number;
  mean_kinship: number | null;
  band: Band | null;
  band_reason: BandReason;
  in_reference: boolean;
  alive: boolean;
  pedigree_completeness: number;
  reference_size: number;
  definition_version: number;
  preliminary: boolean;
  stale: boolean;
}

export const BAND_LABELS: Record<Band, string> = {
  A: "Mycket värdefull för aveln",
  B: "Värdefull för aveln",
  C: "Som rasen i genomsnitt",
  D: "Väl representerad",
  E: "Starkt representerad",
};

export const BAND_REASON_TEXT: Record<
  "outside_genebank" | "incomplete_pedigree" | "small_reference",
  string
> = {
  outside_genebank: "Såld utanför genbanken",
  incomplete_pedigree: "Stamtavlan är för ofullständig för ett band",
  small_reference: "För få djur i avelsstammen för band",
};

export const percent = (x: number, digits = 1) =>
  `${(x * 100).toLocaleString("sv-SE", { minimumFractionDigits: digits, maximumFractionDigits: digits })}\u00a0%`;
