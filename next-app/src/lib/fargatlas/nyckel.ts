// The determination key, from the atlas package through the API (the operations repo builds and checks it): one
// question at a time, each answer with a fixed id that leads to another question or ends in a colour number.
export interface Svar {
  id: string;
  text: string;
  till: string | number;
  hjalp?: string;
  anteckning?: string;
}

export interface Fraga {
  text: string;
  hjalp?: string | null;
  svar: Svar[];
}

export interface Nyckel {
  version?: string;
  start: string;
  fragor: Record<string, Fraga>;
  efter_numret?: { id: string; text: string; ja: string }[];
  grupper: { id: string; namn: string; nummer: number[] }[];
}

export type Steg = { fraga: string } | { nummer: number; anteckning?: string };

/** Follows the answers from the start: the question the path stops at, or the number it ends in. */
export function vandra(svarIds: string[], nyckel: Nyckel): Steg {
  let steg: string | number = nyckel.start;
  let anteckning: string | undefined;
  for (const id of svarIds) {
    if (typeof steg === "number") throw new Error(`${id} efter numret ${steg}`);
    const svar: Svar | undefined = nyckel.fragor[steg]?.svar.find(
      (s) => s.id === id,
    );
    if (!svar) throw new Error(`${id} är inget svar på ${steg}`);
    steg = svar.till;
    anteckning = svar.anteckning;
  }
  return typeof steg === "number"
    ? { nummer: steg, ...(anteckning && { anteckning }) }
    : { fraga: steg };
}

/** The questions in reading order for the printed key: the start first, then by id as people number them (q9b before q10). */
export function fragorIOrdning(nyckel: Nyckel): string[] {
  const ovriga = Object.keys(nyckel.fragor)
    .filter((id) => id !== nyckel.start)
    .sort((a, b) => a.localeCompare(b, "sv", { numeric: true }));
  return [nyckel.start, ...ovriga];
}

/**
 * Why the guide cannot use this key, or null when it can: a key of the wrong shape, a missing start, a question
 * without answers, an answer that leads nowhere, or a path that comes back to a question it has passed (the guide
 * would go round for ever). It never throws, since the page and the colour picker call it while rendering.
 */
export function kontrollera(nyckel: Nyckel | null | undefined): string | null {
  try {
    return brister(nyckel);
  } catch {
    return "nyckeln har fel form";
  }
}

function brister(nyckel: Nyckel | null | undefined): string | null {
  if (!nyckel?.fragor || typeof nyckel.fragor !== "object")
    return "nyckeln saknar frågor";
  if (!(nyckel.start in nyckel.fragor))
    return "nyckeln saknar sin första fråga";
  if (nyckel.efter_numret !== undefined && !Array.isArray(nyckel.efter_numret))
    return "frågorna efter numret har fel form";
  for (const [id, fraga] of Object.entries(nyckel.fragor)) {
    if (!Array.isArray(fraga?.svar) || fraga.svar.length === 0)
      return `${id} saknar svar`;
    for (const s of fraga.svar) {
      if (typeof s?.id !== "string" || typeof s.text !== "string")
        return `ett svar på ${id} har fel form`;
      if (typeof s.till === "number") continue;
      if (typeof s.till !== "string") return `${s.id} leder ingenstans`;
      if (!(s.till in nyckel.fragor))
        return `${s.id} leder till ${s.till}, som inte finns`;
    }
  }
  const farg: Record<string, "gra" | "klar"> = {};
  const slinga = (q: string): string | null => {
    farg[q] = "gra";
    for (const s of nyckel.fragor[q].svar) {
      if (typeof s.till === "number") continue;
      if (farg[s.till] === "gra") return `${q} leder tillbaka till ${s.till}`;
      if (!farg[s.till]) {
        const fel = slinga(s.till);
        if (fel) return fel;
      }
    }
    farg[q] = "klar";
    return null;
  };
  return slinga(nyckel.start);
}
