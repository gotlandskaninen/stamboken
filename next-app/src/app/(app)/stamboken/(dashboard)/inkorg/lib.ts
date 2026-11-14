// The intake queue ("Inkorgen"): types, labels and the rules the two pages
// share. The API contract is docs/inkorg.md; Flask decides, this only chooses
// what to offer.
import type { NumberCheck } from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";
import { OUTSIDE_GENEBANK_HERDS } from "@/utils/saleRules";

export type ItemState =
  | "ny"
  | "tagen"
  | "vantar_uppfodare"
  | "vantar_foralder"
  | "hos_genbanksansvarig"
  | "ofullstandig"
  | "klar"
  | "dubblett"
  | "skrap";

export type Person = { id: number; name: string };

export interface InboxItem {
  id: number;
  kind: string;
  state: ItemState;
  genebank_id: number | null;
  herd: string | null;
  received_at: string;
  state_changed_at: string;
  closed_at: string | null;
  sender: Person | null;
  assigned_to: Person | null;
  assigned_at: string | null;
  duplicate_of: number | null;
  stalled: boolean;
  missing_proof: boolean;
  ref_type: string | null;
  ref_id: number | null;
  has_message: boolean;
  documents: number;
  documents_done: number;
}

export type DocStatus =
  | "ny"
  | "vantar_foralder"
  | "sparad"
  | "klar"
  | "avfardad";
export type DocType = "intyg" | "bevis" | "arsblankett" | "annat";
export type Rect = { x: number; y: number; w: number; h: number };

export interface InboxDocument {
  id: number;
  status: DocStatus;
  mime: string;
  warnings: string[];
  duplicates: { item_id: number; document_id: number }[];
  doc_type: DocType;
  cert_format: string | null;
  rotation: number;
  mask_rects: Rect[] | null;
  mask_suggestion: Rect[] | null;
  waiting_for: string[] | null;
  proposal: Partial<CertForm> | null;
  individual: string | null;
  has_copy: boolean;
}

export interface InboxEvent {
  id: number;
  at: string;
  kind: string;
  user: Person | null;
  detail: Record<string, unknown> | null;
}

export interface InboxDetail extends Omit<InboxItem, "documents"> {
  message: string | null;
  documents: InboxDocument[];
  events: InboxEvent[];
}

export interface QueueList {
  items: InboxItem[];
  total: number;
  counts: Partial<Record<ItemState, number>>;
}

/** An RFC 9457 problem as a server action hands it to the client. */
export type Problem = {
  status: number;
  title: string;
  detail: string;
  extensions?: Record<string, unknown>;
};

export const OPEN_STATES: ItemState[] = [
  "ny",
  "tagen",
  "vantar_uppfodare",
  "vantar_foralder",
  "hos_genbanksansvarig",
  "ofullstandig",
];
export const CLOSED_STATES: ItemState[] = ["klar", "dubblett", "skrap"];
// The states in which the item has a handler (app/utils/inbox.py HELD_STATES).
const HELD_STATES: ItemState[] = [
  "tagen",
  "vantar_uppfodare",
  "vantar_foralder",
  "ofullstandig",
];

export const STATE_LABEL: Record<ItemState, string> = {
  ny: "Ny",
  tagen: "Tagen",
  vantar_uppfodare: "Väntar på uppfödaren",
  vantar_foralder: "Väntar på förälder",
  hos_genbanksansvarig: "Hos genbanksansvarig",
  ofullstandig: "Ofullständig",
  klar: "Klar",
  dubblett: "Dubblett",
  skrap: "Skräp",
};

export const KIND_LABEL: Record<string, string> = {
  upload: "Uppladdning",
  mail: "Mejl",
  meddelande: "Meddelande",
  kontroll: "Kontroll",
  avisering: "Avisering",
};

export const DOC_STATUS_LABEL: Record<DocStatus, string> = {
  ny: "Att lägga in",
  vantar_foralder: "Väntar på förälder",
  sparad: "Inlagt, maskning kvar",
  klar: "Klart",
  avfardad: "Avfärdat",
};

export const DOC_TYPE_LABEL: Record<DocType, string> = {
  intyg: "Intyg",
  bevis: "Bevis",
  arsblankett: "Årsblankett",
  annat: "Annat",
};

export const CERT_FORMAT_LABEL: Record<string, string> = {
  handskrivet: "Handskrivet (grönt)",
  datorskrivet: "Datorskrivet",
  v1_pdf: "Utskriven PDF",
  intyg_b: "Intyg B (nytt, tomt)",
  digitalt_v2: "Digitalt med QR-kod",
};

export const WARNING_LABEL: Record<string, string> = {
  lag_upplosning: "låg upplösning",
  suddig: "kan vara oskarp",
  for_mork: "för mörk",
  for_ljus: "för ljus",
};

export const kindLabel = (kind: string) => KIND_LABEL[kind] ?? kind;

/** Time since `from`, in plain words. */
export function waited(from: string, now = Date.now()): string {
  const hours = (now - Date.parse(from)) / 3_600_000;
  if (!(hours >= 1)) return "under en timme";
  if (hours < 48) {
    const h = Math.floor(hours);
    return h === 1 ? "1 timme" : `${h} timmar`;
  }
  return `${Math.floor(hours / 24)} dagar`;
}

// ---------------------------------------------------------------------------
// Who may do what (docs/inkorg.md "Lägen" and "Roller")

export type QueueUser = {
  id: number;
  is_admin: boolean;
  is_manager: number[] | null;
};

/** A manager of the genebank, or an admin; an item without genebank: any manager. */
export function manages(user: QueueUser, genebankId: number | null): boolean {
  const managed = user.is_manager ?? [];
  if (user.is_admin) return true;
  return genebankId === null
    ? managed.length > 0
    : managed.includes(genebankId);
}

export type ItemAction =
  | "ta"
  | "arbeta_vidare"
  | "ta_over"
  | "tilldela"
  | "hos_genbanksansvarig"
  | "vantar_foralder"
  | "ofullstandig"
  | "dubblett"
  | "skrap"
  | "oppna";

export const ACTION_LABEL: Record<ItemAction, string> = {
  ta: "Jag tar den",
  arbeta_vidare: "Arbeta vidare",
  ta_over: "Ta över",
  tilldela: "Tilldela",
  hos_genbanksansvarig: "Lämna till genbanksansvarig",
  vantar_foralder: "Väntar på förälder",
  ofullstandig: "Ofullständig",
  dubblett: "Dubblett",
  skrap: "Skräp",
  oppna: "Öppna igen",
};

type ItemFacts = Pick<InboxItem, "state" | "assigned_to" | "genebank_id">;

const isMine = (item: ItemFacts, user: QueueUser) =>
  item.assigned_to?.id === user.id;

/**
 * The actions the transition table allows this user on this item. "Arbeta
 * vidare" is …/ta by the handler of a waiting item: it becomes "tagen" again.
 */
export function itemActions(item: ItemFacts, user: QueueUser): ItemAction[] {
  const actions: ItemAction[] = [];
  const mine = isMine(item, user);
  const boss = manages(user, item.genebank_id);
  if (OPEN_STATES.includes(item.state)) {
    if (!item.assigned_to) actions.push("ta");
    else if (!mine) actions.push("ta_over");
    else if (item.state !== "tagen") actions.push("arbeta_vidare");
    if (boss) actions.push("tilldela");
  }
  if (mine && item.state === "tagen")
    actions.push("hos_genbanksansvarig", "vantar_foralder", "ofullstandig");
  if (mine && HELD_STATES.includes(item.state))
    actions.push("dubblett", "skrap");
  if (CLOSED_STATES.includes(item.state) && boss) actions.push("oppna");
  return actions;
}

/** PATCH …/dokument and …/maskning: the handler, in a state with a handler. */
export const canEditDocuments = (item: ItemFacts, user: QueueUser) =>
  isMine(item, user) && HELD_STATES.includes(item.state);

/** …/spara and …/overlat: the handler, in "tagen", and no ref_type. */
export const canSave = (
  item: ItemFacts & Pick<InboxItem, "ref_type">,
  user: QueueUser,
) => isMine(item, user) && item.state === "tagen" && item.ref_type === null;

// ---------------------------------------------------------------------------
// Documents

const OPEN_DOCS: DocStatus[] = ["ny", "sparad"];

/**
 * The next document that needs work, from `currentId` on and round the list:
 * the current one first while it is still open (a saved certificate still
 * needs its masking), unless `skipCurrent` ("Hoppa över"). A document waiting
 * for a parent is not open. null when nothing is left.
 */
export function nextOpenDocument(
  docs: Pick<InboxDocument, "id" | "status">[],
  currentId: number | null,
  skipCurrent = false,
): number | null {
  const start = Math.max(
    0,
    docs.findIndex((d) => d.id === currentId),
  );
  for (let i = 0; i < docs.length; i++) {
    const doc = docs[(start + i) % docs.length];
    if (skipCurrent && doc.id === currentId) continue;
    if (OPEN_DOCS.includes(doc.status)) return doc.id;
  }
  return null;
}

// ---------------------------------------------------------------------------
// What a certificate shows (…/spara) and a sale (…/overlat)

/** One string per field on the certificate (docs/inkorg.md, "Spara det intyget visar"). */
export type CertForm = {
  paper_number: string;
  paper_certificate: string;
  name: string;
  sex: "" | "female" | "male";
  birth_date: string;
  color: string;
  litter_size: string;
  litter_size6w: string;
  mother: string;
  father: string;
  /** pappersintyg: the rabbit's number in Stamboken. */
  individual: string;
};

export type SaveMode = "ny_kanin" | "pappersintyg";

const EMPTY_FORM: CertForm = {
  paper_number: "",
  paper_certificate: "",
  name: "",
  sex: "",
  birth_date: "",
  color: "",
  litter_size: "",
  litter_size6w: "",
  mother: "",
  father: "",
  individual: "",
};

/** The form's first values: empty, or what the image reading proposes. */
export function initialCertForm(proposal: Partial<CertForm> | null): CertForm {
  const form = { ...EMPTY_FORM };
  for (const key of Object.keys(EMPTY_FORM) as (keyof CertForm)[]) {
    const value = proposal?.[key];
    if (value !== undefined && value !== null)
      Object.assign(form, { [key]: String(value) });
  }
  return form;
}

const number = (s: string) => s.trim().toUpperCase();
const count = (s: string) => (/^\d+$/.test(s.trim()) ? Number(s) : undefined);

export type NumberResolution = {
  expected_number: string | null;
  choice: "use_stamboken_number";
};

/** The body of POST …/spara. Empty optional fields are left out. */
export function buildSavePayload(
  mode: SaveMode,
  form: CertForm,
  resolution?: NumberResolution,
): Record<string, unknown> {
  if (mode === "pappersintyg") {
    return {
      action: "pappersintyg",
      individual: number(form.individual),
      paper_certificate: form.paper_certificate.trim(),
      paper_number: number(form.paper_number),
    };
  }
  const payload: Record<string, unknown> = {
    action: "ny_kanin",
    paper_number: number(form.paper_number),
    paper_certificate: form.paper_certificate.trim(),
    mother: number(form.mother),
    father: number(form.father),
    birth_date: form.birth_date,
  };
  if (form.name.trim()) payload.name = form.name.trim();
  if (form.sex) payload.sex = form.sex;
  if (form.color.trim()) payload.color = form.color.trim();
  const born = count(form.litter_size);
  const alive = count(form.litter_size6w);
  if (born !== undefined) payload.litter_size = born;
  if (alive !== undefined) payload.litter_size6w = alive;
  if (resolution) payload.resolution = resolution;
  return payload;
}

export type SaleForm = {
  individual: string;
  herd: string;
  outside: boolean;
  date: string;
};

/** GX1 or MX1: the genebank's herd for rabbits sold outside the association. */
export function outsideHerd(individual: string): string | null {
  const letter = individual.trim().charAt(0).toUpperCase();
  return (
    (letter && OUTSIDE_GENEBANK_HERDS.find((h) => h.startsWith(letter))) || null
  );
}

/** The body of POST …/overlat. The herd field may hold a picked label, "G1274 – Name": the code is its first word. */
export function buildSalePayload(form: SaleForm) {
  const individual = number(form.individual);
  return {
    individual,
    herd: form.outside
      ? (outsideHerd(individual) ?? "")
      : number(form.herd.trim().split(/\s/)[0]),
    date: form.date,
  };
}

// ---------------------------------------------------------------------------
// API errors next to their field. Problems carry no field name, so this goes
// by title where there is one and by the API's exact wording otherwise.

export type FieldKey = keyof CertForm | keyof SaleForm;

const DETAIL_FIELDS: [RegExp, FieldKey][] = [
  [/^Välj mor och far|^Modern /, "mother"],
  [/^Fadern /, "father"],
  [/levande vid 6 veckor|litter_size6w/i, "litter_size6w"],
  [/antal födda/i, "litter_size"],
  [/^Födelsedatum/, "birth_date"],
  [/^name must/, "name"],
  [
    /intygsnumret|Intygsnummer krävs|paper_certificate|certificate already exists/i,
    "paper_certificate",
  ],
  [/som det står på pappersintyget|^Individnumret ska skrivas/, "paper_number"],
  [/färg|color/i, "color"],
  [/^Kaninen finns inte/, "individual"],
  [/köparens besättning/, "herd"],
];

export function problemField(problem: Problem): FieldKey | null {
  switch (problem.title) {
    case "number_conflict":
      return "paper_number";
    case "too_young":
    case "litter_order_conflict":
      return "birth_date";
    case "Ogiltig försäljning":
      // The sale rules: a date too early or in the future, else the buyer herd.
      return /datum/i.test(problem.detail) ? "date" : "herd";
    case "Conflict":
      // Also "Mor eller far ändrades samtidigt": that one is for the whole form.
      return /certificate number/i.test(problem.detail)
        ? "paper_certificate"
        : null;
  }
  return DETAIL_FIELDS.find(([re]) => re.test(problem.detail))?.[1] ?? null;
}

// The registration answers some litter rules with a bare key as its detail;
// RegisterRabbitDialog words them the same way (messages/sv.json addRabbit.*).
const RULE_TEXT: Record<string, string> = {
  max_reached: "Kullen är full — max 9 kaniner per kull.",
  litter_size: "Antal registrerade kaniner matchar redan kullstorleken.",
  litter_size6w_required:
    "Fyll i hur många kaniner som var levande efter 6 veckor innan intyget kan sparas.",
  certificate_quota_exceeded:
    "Kullen har inga intyg kvar att ge (antal levande efter 6 veckor).",
  roster_alive_exceeds_6w:
    "Kullistan har fler levande ungar än antalet levande vid 6 veckor. Markera de döda ungarna i kullistan först.",
};

/** The problem's detail for the user: rule keys in words, everything else as the API wrote it. */
export const problemText = (problem: Problem) =>
  RULE_TEXT[problem.detail] ?? problem.detail;

/** The number check in a 409 number_conflict, for NumberConflictDialog. */
export function numberCheckOf(problem: Problem): NumberCheck | null {
  if (problem.status !== 409 || problem.title !== "number_conflict")
    return null;
  const { check_status, ...fields } = problem.extensions ?? {};
  return {
    ...(fields as Omit<NumberCheck, "status">),
    status: check_status as NumberCheck["status"],
  };
}

/** The people a manager can pick: you, everyone the list shows, and `extra`. */
export function people(
  me: Person,
  items: InboxItem[],
  extra: Person[] = [],
): Person[] {
  const byId = new Map<number, Person>([[me.id, me]]);
  for (const p of [...items.map((i) => i.assigned_to), ...extra])
    if (p && !byId.has(p.id)) byId.set(p.id, p);
  return [...byId.values()].sort((a, b) => a.name.localeCompare(b.name, "sv"));
}
