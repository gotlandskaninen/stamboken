// GET /api/v2/fargatlas: the colours from the database, with the atlas package's texts and photos.
export interface AtlasFoto {
  id: string;
  fotograf: string | null;
  bildtext: string | null;
}

export interface AtlasFarg {
  id: number;
  name: string;
  comment: string | null;
  genebank: string;
  beskrivning: string | null;
  skiljs_fran: string | null;
  foton: AtlasFoto[];
}

export interface Grupp {
  id: string;
  namn: string;
  nummer: number[];
}

/** The determination key, from the atlas package (never from the repo). The page reads its groups. */
export interface AtlasNyckel {
  version?: string;
  start: string;
  fragor: Record<string, unknown>;
  grupper: Grupp[];
}

export interface Fargatlas {
  version: string | null;
  grupper: Record<string, { beskrivning?: string | null } | null>;
  farger: AtlasFarg[];
  nyckel: AtlasNyckel | null;
}

/** The key's groups; without a key, one group per genebank with its colours in number order. */
export function grupperFor(atlas: Fargatlas): Grupp[] {
  if (atlas.nyckel) return atlas.nyckel.grupper;
  const per = new Map<string, number[]>();
  for (const f of atlas.farger)
    per.set(f.genebank, [...(per.get(f.genebank) ?? []), f.id]);
  return [...per].map(([namn, nummer]) => ({
    id: `genbank-${nummer[0]}`,
    namn,
    nummer,
  }));
}

/** The photo's address on the API the page reads from (`/api`, or the demo API in test mode). */
export function fotoUrl(fotoBas: string, id: string, storlek: 480 | 1600) {
  return `${fotoBas}/v2/fargatlas/foto/${encodeURIComponent(id)}?storlek=${storlek}`;
}
