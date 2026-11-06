// Provparning (test mating) — pure helpers shared by the page, the form and
// vitest. Contract: POST /api/v2/testbreed (app/blueprints/testbreed_v2.py).
import type {
  Individual,
  PaginatedIndividualItem,
  PedigreeNode,
} from "@/redux/api/apiSlice";

export const MAX_MALES = 10;

export type Verdict = "good" | "check" | "high";
export type Relation = "parent_child" | "full_siblings" | "half_siblings";

export interface Thresholds {
  good_max: number;
  check_max: number;
}

export interface AnimalSummary {
  number: string | null;
  name: string | null;
  f: number | null;
  mk: number | null;
  /**
   * Partner + two ancestor generations, already filtered server-side (voided
   * and other-genebank ancestors are null). An unregistered partner is an
   * `unregistered` node over its stated parents.
   */
  pedigree: PedigreeNode;
}

export interface CommonAncestor {
  number: string;
  name: string | null;
  /** [generations from the male, generations from the female]; 0 = the animal itself */
  generations: [number, number];
}

export interface TestbreedResult {
  male: AnimalSummary;
  offspring_f: number;
  verdict: Verdict;
  relation: Relation | null;
  common_ancestors: CommonAncestor[];
}

export interface TestbreedResponse {
  genebank_id: number;
  thresholds: Thresholds;
  female: AnimalSummary;
  results: TestbreedResult[];
}

export interface ParentsPayload {
  mother: string | null;
  father: string | null;
}

export type MalePayload =
  | { number: string }
  | { number: null; parents: ParentsPayload };

export interface TestbreedRequest {
  genebank_id: number;
  female: string | null;
  female_parents?: ParentsPayload;
  males: MalePayload[];
}

/** One side of the mating as held by the form. */
export interface AnimalInput {
  /** Stable React key (males can be added/removed). */
  key: string;
  picked: PaginatedIndividualItem | null;
  /** "Den är inte registrerad än" — use mother/father instead of `picked`. */
  unregistered: boolean;
  mother: PaginatedIndividualItem | null;
  father: PaginatedIndividualItem | null;
}

/** Stub list item for an individual known only by number/name (URL prefill). */
export function pickedFromIndividual(
  ind: Pick<Individual, "number" | "name" | "sex" | "herd" | "alive">,
): PaginatedIndividualItem {
  const herd = typeof ind.herd === "string" ? ind.herd : (ind.herd?.herd ?? "");
  return {
    number: ind.number ?? "",
    name: ind.name ?? null,
    sex: ind.sex ?? null,
    birth_date: null,
    status: ind.alive === false ? "död" : "active",
    herd,
    color: null,
    has_photo: false,
    litter_size: null,
    litter_size6w: null,
    mother_number: null,
    mother_name: null,
    father_number: null,
    father_name: null,
  };
}

// ---------------------------------------------------------------------------
// Verdict + number formatting
// ---------------------------------------------------------------------------

export function verdictFor(f: number, thresholds: Thresholds): Verdict {
  if (f <= thresholds.good_max) return "good";
  if (f <= thresholds.check_max) return "check";
  return "high";
}

/** Swedish decimal comma, fixed number of decimals, no unit. */
export function formatDecimal(value: number, decimals = 1): string {
  return value.toFixed(decimals).replace(".", ",");
}

/** "3,1 %" with a non-breaking space before the percent sign. */
export function formatPercent(value: number, decimals = 1): string {
  return `${formatDecimal(value, decimals)} %`;
}

/**
 * Offspring F for display: one decimal, unless rounding to one decimal would
 * land on the other side of a verdict boundary than the exact value
 * (4,04 % is "Utred närmare" — "4,0 %" next to that badge would look wrong).
 */
export function formatOffspringF(f: number, thresholds: Thresholds): string {
  const rounded = Math.round(f * 10) / 10;
  const same = verdictFor(rounded, thresholds) === verdictFor(f, thresholds);
  return formatPercent(f, same ? 1 : 2);
}

// ---------------------------------------------------------------------------
// URL <-> selection
// ---------------------------------------------------------------------------

export interface ProvparningParams {
  genebank: number | null;
  hona: string | null;
  hane: string[];
}

type RawParams = Record<string, string | string[] | undefined>;

const first = (v: string | string[] | undefined) =>
  Array.isArray(v) ? v[0] : v;
const list = (v: string | string[] | undefined) =>
  v === undefined ? [] : Array.isArray(v) ? v : [v];

/** Parse `?genebank=1&hona=G1-1&hane=G1-2&hane=G1-3` (deduped, max MAX_MALES). */
export function parseProvparningParams(raw: RawParams): ProvparningParams {
  const gb = Number(first(raw.genebank));
  const hona = first(raw.hona)?.trim() || null;
  const hane: string[] = [];
  for (const h of list(raw.hane)) {
    const n = h.trim();
    if (n && !hane.includes(n) && hane.length < MAX_MALES) hane.push(n);
  }
  return {
    genebank: Number.isInteger(gb) && gb > 0 ? gb : null,
    hona,
    hane,
  };
}

/** Inverse of parse; empty selections are omitted. Returns "" when nothing to say. */
export function serializeProvparningParams(p: ProvparningParams): string {
  const qs = new URLSearchParams();
  if (p.genebank != null) qs.set("genebank", String(p.genebank));
  if (p.hona) qs.set("hona", p.hona);
  for (const h of p.hane) qs.append("hane", h);
  return qs.toString();
}

/** Parse a query string or URLSearchParams (see parseProvparningParams). */
export function paramsFromSearch(
  search: string | URLSearchParams,
): ProvparningParams {
  const qs = typeof search === "string" ? new URLSearchParams(search) : search;
  return parseProvparningParams({
    genebank: qs.get("genebank") ?? undefined,
    hona: qs.get("hona") ?? undefined,
    hane: qs.getAll("hane"),
  });
}

/** What the server page made of one URL: the query it parsed and what it resolved. */
export interface ServerSelection {
  /** serializeProvparningParams() of the URL the server rendered. */
  query: string;
  /** Its selection after dropping invisible, wrong-sex and other-genebank numbers. */
  selection: ProvparningParams;
}

/**
 * The registered selection a URL stands for. For the very URL the server
 * rendered, that is the server's resolved selection (numbers the viewer may
 * not use are dropped, the genebank is inferred). Any other URL was written
 * by the form itself from such a selection plus autocomplete picks, so it is
 * taken as is; only an unknown genebank falls back to the server's.
 */
export function effectiveSelection(
  url: ProvparningParams,
  server: ServerSelection,
  accessibleGenebanks: number[],
): ProvparningParams {
  if (serializeProvparningParams(url) === server.query) return server.selection;
  const genebank =
    url.genebank != null && accessibleGenebanks.includes(url.genebank)
      ? url.genebank
      : server.selection.genebank;
  return { ...url, genebank };
}

/**
 * The male list after slot edit `old -> next` (null = empty): replaces `old`
 * in place, appends `next` when the slot held nothing, removes `old` when
 * cleared. A male that is already chosen is never added twice; picking the
 * slot's own male again changes nothing.
 */
export function replaceMale(
  hane: string[],
  old: string | null,
  next: string | null,
): string[] {
  if (old === next) return hane;
  const at = old == null ? -1 : hane.indexOf(old);
  const add = next != null && !hane.includes(next);
  if (at < 0) return add ? [...hane, next!] : hane;
  return add
    ? hane.map((n, i) => (i === at ? next! : n))
    : hane.filter((_, i) => i !== at);
}

/**
 * One picker slot as the form lays it out. A registered slot names its
 * number, which only counts while the URL still has it. An unregistered slot
 * ("inte registrerad än") lives only here; `number` keeps its earlier pick so
 * switching back restores it.
 */
export interface Slot {
  key: string;
  number: string | null;
  unregistered: boolean;
  mother: PaginatedIndividualItem | null;
  father: PaginatedIndividualItem | null;
}

export function emptySlot(key: string): Slot {
  return { key, number: null, unregistered: false, mother: null, father: null };
}

/**
 * The male slots to show: the URL decides WHICH males are chosen, the local
 * layout only WHERE. Registered slots whose number left the URL disappear
 * (the URL wins), URL males without a slot are appended, empty and
 * unregistered slots stay. Never returns an empty list.
 */
export function deriveMaleSlots(slots: Slot[], hane: string[]): Slot[] {
  const inUrl = new Set(hane);
  const placed = new Set<string>();
  const out: Slot[] = [];
  for (const s of slots) {
    if (s.unregistered || s.number == null) out.push(s);
    else if (inUrl.has(s.number) && !placed.has(s.number)) {
      placed.add(s.number);
      out.push(s);
    }
  }
  const keys = new Set(out.map((s) => s.key));
  const freshKey = (base: string) => {
    let key = base;
    while (keys.has(key)) key += "'";
    keys.add(key);
    return key;
  };
  for (const n of hane) {
    if (!placed.has(n))
      out.push({ ...emptySlot(freshKey(`hane:${n}`)), number: n });
  }
  if (out.length === 0) out.push(emptySlot(freshKey("hane")));
  return out;
}

/**
 * The male slot layouts the form made: `slots` for the URL `query` it wrote
 * last, and — only while that write has not reached the router yet — `base`
 * for the URL `before` it.
 */
export interface SlotLayout {
  /** null once the URL has been seen at `query` (see settleLayout). */
  before: string | null;
  base: Slot[];
  query: string;
  slots: Slot[];
}

export const EMPTY_LAYOUT: SlotLayout = {
  before: null,
  base: [],
  query: "",
  slots: [],
};

/**
 * The layout to show for the URL `query`, whichever of the form's state and
 * the router's replaceState commits first: while the URL still reads
 * `before`, the layout from before the edit; at `query`, the one after it;
 * any other URL (a navigation) gets the latest one. The layout only places
 * slots — deriveMaleSlots() re-checks it against the URL's males on every
 * render, so a layout never shows a male the URL does not have.
 */
export function layoutFor(layout: SlotLayout, query: string): Slot[] {
  return query === layout.before && query !== layout.query
    ? layout.base
    : layout.slots;
}

/**
 * The guard only bridges the gap while the router still shows the URL from
 * before the write. Once the router reads anything else — the write itself, or
 * a later URL that superseded it (another edit in the same task, a navigation)
 * — or the browser (`browser`, read after a commit) is back at that URL, the
 * pre-write layout is history and must not apply when a later navigation
 * happens to lead back to that URL. The browser check is needed because the
 * router may never commit the write: Next applies a replaceState in a
 * transition, and a navigation in the same transition supersedes it.
 */
export function settleLayout(
  layout: SlotLayout,
  query: string,
  browser: string,
): SlotLayout {
  return layout.before !== null &&
    (query !== layout.before || browser === layout.before)
    ? { ...layout, before: null, base: [] }
    : layout;
}

/**
 * Slot `key` as the latest edit left it, for the URL `from` (with males
 * `hane`) — not as some earlier render showed it. Undefined once removed.
 */
export function slotNow(
  layout: SlotLayout,
  from: string,
  hane: string[],
  key: string,
): Slot | undefined {
  return deriveMaleSlots(layoutFor(layout, from), hane).find(
    (s) => s.key === key,
  );
}

/** Apply a slot edit made while the URL read `from` and that wrote `to`. */
export function editLayout(
  layout: SlotLayout,
  from: string,
  to: string,
  hane: string[],
  edit: (slots: Slot[]) => Slot[],
): SlotLayout {
  const base = deriveMaleSlots(layoutFor(layout, from), hane);
  const slots = edit(base);
  // Nothing written: no pending write to bridge.
  if (from === to) return { before: null, base: [], query: to, slots };
  return { before: from, base, query: to, slots };
}

/** `map` plus `items` keyed by number; the same map when nothing is new. */
export function withDetails(
  map: ReadonlyMap<string, PaginatedIndividualItem>,
  items: (PaginatedIndividualItem | null)[],
): ReadonlyMap<string, PaginatedIndividualItem> {
  const fresh = items.filter(
    (it): it is PaginatedIndividualItem => !!it && map.get(it.number) !== it,
  );
  if (fresh.length === 0) return map;
  const next = new Map(map);
  for (const it of fresh) next.set(it.number, it);
  return next;
}

// ---------------------------------------------------------------------------
// Request building
// ---------------------------------------------------------------------------

function parentsOf(a: AnimalInput): ParentsPayload | null {
  if (!a.mother && !a.father) return null;
  return {
    mother: a.mother?.number ?? null,
    father: a.father?.number ?? null,
  };
}

/**
 * The request to send, or null while the selection is incomplete (needs a
 * female — registered or via at least one parent — and one or more males).
 * Males that are still empty are skipped.
 */
export function buildTestbreedRequest(
  genebankId: number | null,
  female: AnimalInput,
  males: AnimalInput[],
): TestbreedRequest | null {
  if (genebankId == null) return null;

  const req: TestbreedRequest = {
    genebank_id: genebankId,
    female: null,
    males: [],
  };
  if (female.unregistered) {
    const parents = parentsOf(female);
    if (!parents) return null;
    req.female_parents = parents;
  } else {
    if (!female.picked) return null;
    req.female = female.picked.number;
  }

  for (const m of males) {
    if (m.unregistered) {
      const parents = parentsOf(m);
      if (parents) req.males.push({ number: null, parents });
    } else if (m.picked) {
      req.males.push({ number: m.picked.number });
    }
  }
  return req.males.length > 0 ? req : null;
}

/**
 * More comparisons than one calculation allows. Possible after a navigation
 * that brings registered males on top of unregistered ones kept locally.
 */
export function tooManyMales(req: TestbreedRequest | null): boolean {
  return req !== null && req.males.length > MAX_MALES;
}

// ---------------------------------------------------------------------------
// Result presentation
// ---------------------------------------------------------------------------

/** Cards sorted by offspring F ascending; ties keep the order the user chose. */
export function sortResults<T extends { offspring_f: number }>(
  results: T[],
): { result: T; index: number }[] {
  return results
    .map((result, index) => ({ result, index }))
    .sort(
      (a, b) =>
        a.result.offspring_f - b.result.offspring_f || a.index - b.index,
    );
}

export const VERDICT_LABEL: Record<Verdict, string> = {
  good: "Bra",
  check: "Utred närmare",
  high: "Hög inavel",
};

export const RELATION_LABEL: Record<Relation, string> = {
  parent_child: "Djuren är förälder och barn.",
  full_siblings: "Djuren är helsyskon.",
  half_siblings: "Djuren är halvsyskon.",
};

/** Where a common ancestor sits, e.g. "2 led från hanen, 1 led från honan". */
export function describeGenerations([male, female]: [number, number]): string {
  const side = (n: number, self: string, who: string) =>
    n === 0 ? self : `${n} led från ${who}`;
  return `${side(male, "är hanen själv", "hanen")}, ${side(female, "är honan själv", "honan")}`;
}

/**
 * Monotonic request ids: `next()` starts an invocation and supersedes every
 * earlier one; only the latest id may apply its outcome.
 */
export function createSequence() {
  let current = 0;
  return {
    next: () => ++current,
    isLatest: (id: number) => id === current,
  };
}
