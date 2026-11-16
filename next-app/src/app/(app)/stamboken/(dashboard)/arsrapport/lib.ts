// Shapes of /api/v2/arsrapport/* and the form's own logic. Kept free of React
// and of server actions so the paper page (Task 14) and the status view
// (Task 15) can reuse it.
import { newOperationId } from "@/lib/herdTracking";
import type { Mode } from "@/lib/mode";
import type { InboxDetail } from "../inkorg/lib";

export type Val = "kvar" | "dod" | "sald" | "ej_angiven";
export type Hull = "low" | "normal" | "high";
export type Membership = "kvar_utan_genbank" | "avsluta_medlemskap";
export type Disease = "myxomatos" | "rvhd" | "koccidios" | "annat";

export interface RabbitView {
  id: number;
  number: string;
  name: string | null;
  sex: string | null;
  color: string | null;
  birth_date: string | null;
  castrated: boolean;
  adult: boolean;
  last_reported: string | null;
  death_date: string | null;
  state: "att_valja" | "redan_rapporterad" | "via_flytt";
  later: { kind: string; date: string } | null;
}

export interface Refusal {
  individual_id: number | null;
  code: string;
  message: string;
}

export interface Villkor {
  hane: boolean;
  hona: boolean;
  kull: boolean;
  i_tid: boolean;
}

export interface Summary {
  kvar: number;
  doda: number;
  salda: number;
  ej_angivna: number;
}

export interface Receipt {
  submission_id: number;
  report_id: number;
  created_at: string;
  source: "login" | "link" | "paper";
  summary: Summary;
  matrikel: string[];
  warnings: Refusal[];
}

export interface DraftData {
  // The whole form, incomplete values included (the server stores a draft's
  // data as it is). The body-shaped keys below stay for a draft the server
  // writes itself, after Dra tillbaka.
  form?: FormState;
  reason: string | null;
  rabbits: Record<string, BodyEntry>;
  ending_genbank: boolean;
  membership_after_end: Membership | null;
  health: "inga" | "ja" | null;
  diseases: Partial<
    Record<
      Disease,
      { antal: number; alder: string | null; namn?: string | null }
    >
  >;
  defects: { individual_id: number; beskrivning: string | null }[];
  message: string;
}

// The form's contact changes, as the API takes them (paper only). Never in a
// draft and never in localStorage: the page keeps them in memory.
export type Utom = "phone" | "email" | "address";
export interface Matrikel {
  adress?: { address?: string; postal_code?: string; city?: string };
  telefon?: string;
  epost?: string;
  konto?: { clearing?: string; konto?: string; bank?: string };
  publicering?: { ja: boolean; utom: Utom[] };
}

export interface Submission extends DraftData {
  submission_key: string;
  revision: number | null;
  // Paper only (a body sent with ?post=)
  inbox_item_id?: number;
  received_on?: string;
  signed_on?: string;
  matrikel?: Matrikel;
}

export interface ReportView {
  herd: {
    id: number;
    herd: string;
    name: string | null;
    genebank_id: number;
    genebank: string;
  };
  year: number;
  round: {
    start_date: string | null;
    deadline: string | null;
    end_date: string | null;
    activated: boolean;
    open: boolean;
  };
  access: "owner" | "caretaker" | "manager" | "admin" | "helper" | "code";
  source: "login" | "link" | "paper";
  can_sell: boolean;
  other_active_herd: boolean;
  rabbits: RabbitView[];
  litters: {
    id: number;
    litter_number: number | null;
    birth_date: string;
    mother: string | null;
    father: string | null;
    litter_size: number | null;
    litter_size6w: number | null;
  }[];
  sales: {
    individual_id: number;
    number: string;
    to_herd: string;
    date: string;
  }[];
  herds: string[];
  report: null | {
    id: number;
    status: string;
    source: string;
    revision: number;
    received_at: string;
    report_date: string;
    on_time: boolean;
    submitted: (Partial<DraftData> & { reason?: string | null }) | null;
    can_change: boolean;
    can_withdraw: boolean;
    withdraw_until: string | null;
    villkor: Villkor;
  };
  draft: null | {
    data: DraftData;
    updated_at: string;
    submission_key: string | null;
    own: boolean;
  };
  item: null | {
    id: number;
    received_at: string;
    state: string;
    account_end: string | null;
  };
}

export interface MyReport {
  herd: string;
  year: number;
  open: boolean;
  status: string | null;
  deadline: string | null;
  end_date: string | null;
}

// The buyer outside the genebank lives in memory only: never in a draft, never
// in localStorage (D10).
export interface Buyer {
  name: string;
  town: string;
}
export interface DodState {
  ar: number;
  manad: number | null;
  dag: number | null;
  slaktad: boolean;
  anteckning: string;
}
export interface SaldState {
  till: string; // "G9002" or "utanfor"
  ar: number;
  manad: number | null;
  dag: number | null;
  kopare: Buyer | null;
}
export interface Entry {
  val: Val | null;
  vikt: string;
  ej_vagd: string | null;
  hull: Hull | null;
  dod: DodState | null;
  sald: SaldState | null;
}
export interface DiseaseState {
  antal: string;
  alder: string;
  namn: string;
}
export interface FormState {
  rabbits: Record<number, Entry>;
  ending: boolean;
  membership: Membership | null;
  health: "inga" | "ja" | null;
  diseases: Record<Disease, DiseaseState>;
  defects: { individual_id: number; beskrivning: string }[];
  message: string;
  reason: string;
}

// The body of one rabbit as the API takes it.
export interface BodyEntry {
  val: Val;
  vikt?: number | string | null;
  ej_vagd?: string | null;
  hull?: Hull | null;
  dod?: Omit<DodState, "manad"> & { manad: number };
  sald?: {
    till: string;
    ar: number;
    manad: number;
    dag: number | null;
    kopare?: Buyer & { contact_consent: false; membership_optin: false };
  };
}

export const SUBMIT_TIMEOUT_MS = 30_000;

// The wording of the blankett's question about the listing in Koharen
// (CONSENT_TEXT_VERSION "2026-11-16" on the server). Only the paper form shows it.
export const CONSENT_TEXT =
  "Får din genbank stå med i Koharens lista över aktiva genbanker? Koharen är föreningens tidning på papper och går bara till medlemmar. Listan gör det lättare för genbankerna att hitta varandra. Den visar innehavarens namn och genbankens nummer, och dessutom postnummer och ort, telefonnummer och e-postadress ur medlemsregistret.";

export const EJ_VAGD_REASONS = [
  "Hann inte väga",
  "Har ingen våg",
  "Dräktig eller digivande",
] as const;

export const HULL_LABELS: Record<Hull, string> = {
  low: "Mager",
  normal: "Normal",
  high: "Fet",
};

export const MONTHS = [
  "januari",
  "februari",
  "mars",
  "april",
  "maj",
  "juni",
  "juli",
  "augusti",
  "september",
  "oktober",
  "november",
  "december",
];

export const DISEASES: { key: Disease; label: string }[] = [
  { key: "myxomatos", label: "Myxomatos" },
  { key: "rvhd", label: "RVHD" },
  { key: "koccidios", label: "Koccidios" },
  { key: "annat", label: "Annat" },
];

// The refusal codes, in the words the error box shows (the server's `message`
// is the fallback for any other code).
export const REFUSAL_TEXT: Record<string, string> = {
  inte_klar: "Välj Finns kvar, Död eller Såld.",
  vikt_saknas: "Vuxna kaniner behöver vikt eller Ej vägd.",
  vikt_ogiltig: "Ange vikten i kilo, till exempel 2,8.",
  rundan_stangd:
    "Rundan är stängd. Kontakta genbanksansvarig om något behöver ändras.",
  inte_innehavare: "Kaninen fanns inte i din besättning 31 december.",
  dodsdatum_ogiltigt:
    "Dödsdatumet kan inte vara före födelsen eller senare än i dag.",
  skrivning_nekad:
    "Stamboken tog inte emot ändringen för kaninen. Genbanksansvarig kan rätta.",
  senare_handelse:
    "Kaninen har en senare händelse i Stamboken. Genbanksansvarig kan rätta.",
  forsaljning_skotare:
    "Försäljningen registreras av ägaren eller genbanksansvarig.",
  kopare_saknas: "Skriv köparens namn och ort.",
  halsa_saknas: "Välj Inga sjukdomsfall eller defekter, eller Ja.",
  ej_angiven_digitalt: "Ej angiven finns bara när en blankett matas in.",
  orsak_kravs: "Skriv varför rapporten ändras.",
  orsak_kopare: "Skriv inte köparens namn i orsaken.",
};
export const CONFLICT_TEXT = "Rapporten har ändrats på en annan enhet";
export const TIMEOUT_TEXT =
  "Vi vet inte om rapporten kom fram. Tryck Försök igen. Den skickas inte två gånger.";

// The fields a Receipt's `matrikel` names, in words (never a value).
export const MATRIKEL_LABEL: Record<string, string> = {
  konto: "konto",
  adress: "adress",
  telefon: "telefon",
  epost: "e-post",
  publicering: "publicering i Koharen",
};

export const refusalText = (r: Refusal) => REFUSAL_TEXT[r.code] ?? r.message;

// The browser copy of an unsent form: one per data environment, and one for the personal link (/rapport), which
// has no environment of its own.
export const localKey = (scope: Mode | "link", herd: string, year: number) =>
  `arsrapport:${scope}:${herd}:${year}`;

// randomUUID is missing over plain http and on phones older than iOS 15.4 or
// Chrome 92; newOperationId falls back to getRandomValues.
export function newKey(): string {
  return newOperationId();
}

// A new key unless the answer is unknown: a retry after a timeout must carry
// the same key, so that a commit whose answer was lost is found again.
export function keyAfter(
  outcome: "ok" | "timeout" | "withdrawn",
  key: string,
): string {
  return outcome === "timeout" ? key : newKey();
}

export const kgText = (kg: number) => String(kg).replace(".", ",");

// "2,8" and "2.8" are kilos; above 100 the user probably typed grams, and
// above 20 (the server's limit) probably a missing decimal comma.
export function parseWeight(text: string): {
  kg: number | null;
  gramsHint: number | null;
  unusual: boolean;
} {
  const t = text.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(t))
    return { kg: null, gramsHint: null, unusual: false };
  const n = Number(t);
  if (n > 20)
    return {
      kg: null,
      gramsHint: Number((n / (n > 100 ? 1000 : 10)).toFixed(3)),
      unusual: false,
    };
  return { kg: n, gramsHint: null, unusual: n < 1 || n > 6.5 };
}

export const EMPTY_ENTRY: Entry = {
  val: null,
  vikt: "",
  ej_vagd: null,
  hull: null,
  dod: null,
  sald: null,
};

const emptyDiseases = (): Record<Disease, DiseaseState> => ({
  myxomatos: { antal: "", alder: "", namn: "" },
  rvhd: { antal: "", alder: "", namn: "" },
  koccidios: { antal: "", alder: "", namn: "" },
  annat: { antal: "", alder: "", namn: "" },
});

export const emptyState = (): FormState => ({
  rabbits: {},
  ending: false,
  membership: null,
  health: null,
  diseases: emptyDiseases(),
  defects: [],
  message: "",
  reason: "",
});

// A choice that still lacks what the API needs counts as no choice.
const complete = (e: Entry) =>
  e.val === "dod"
    ? e.dod?.manad != null
    : e.val === "sald"
      ? !!e.sald?.till && e.sald.manad != null
      : e.val !== null;

// What a half-filled choice still lacks, for the row error (null when nothing
// specific is missing).
export function incompleteText(e: Entry | undefined): string | null {
  if (!e || complete(e)) return null;
  if (e.val === "sald" && !e.sald?.till) return "Ange köparen.";
  if (e.val === "dod" || e.val === "sald") return "Välj månad.";
  return null;
}

// Does an edit (patch over `before`) settle a row's refusal? Only when it
// touches the field the refusal is about, or the row became klar under a local
// check that covers it. Server-only refusals stay until their field changes.
// A death date the server would accept: not after today (Stockholm), not before the birth. Without a day the
// server takes the month's last day, or today if earlier.
export function deathDateOk(
  d: { ar: number; manad: number | null; dag: number | null } | null,
  birth: string | null | undefined,
  today: string = todayStockholm(),
): boolean {
  if (!d || d.manad == null) return true;
  const ym = `${d.ar}-${String(d.manad).padStart(2, "0")}`;
  if (ym > today.slice(0, 7)) return false;
  const last = new Date(Date.UTC(d.ar, d.manad, 0)).getUTCDate();
  let iso = `${ym}-${String(d.dag ?? last).padStart(2, "0")}`;
  if (iso > today) {
    if (d.dag) return false;
    iso = today;
  }
  return !birth || iso >= birth.slice(0, 10);
}

export function editClears(
  code: string,
  before: Entry,
  patch: Partial<Entry>,
  doneAfter: boolean,
  birth?: string | null,
): boolean {
  const date = (
    a?: { ar: number; manad: number | null; dag: number | null } | null,
  ) => (a ? `${a.ar}-${a.manad}-${a.dag}` : "");
  const dateChanged =
    ("dod" in patch && date(patch.dod) !== date(before.dod)) ||
    ("sald" in patch && date(patch.sald) !== date(before.sald));
  switch (code) {
    case "dodsdatum_ogiltigt":
      return (
        dateChanged && deathDateOk({ ...before, ...patch }.dod ?? null, birth)
      );
    case "vikt_saknas":
    case "vikt_ogiltig":
      return (
        ("vikt" in patch && patch.vikt !== before.vikt) ||
        ("ej_vagd" in patch && patch.ej_vagd !== before.ej_vagd) ||
        ("val" in patch && patch.val !== before.val)
      );
    case "kopare_saknas":
      return (
        ("sald" in patch &&
          (patch.sald?.till !== before.sald?.till ||
            patch.sald?.kopare !== before.sald?.kopare)) ||
        ("val" in patch && patch.val !== before.val)
      );
    case "inte_klar":
      return (
        ("val" in patch && patch.val !== before.val) || dateChanged || doneAfter
      );
    default:
      return false;
  }
}

export function isDone(
  r: RabbitView,
  e: Entry | undefined,
  ending: boolean,
): boolean {
  if (ending) return true; // 5.7: an ending genebank needs neither choice nor weight
  if (!e || e.val === null) return r.state !== "att_valja";
  if (e.val === "ej_angiven") return true; // P44: kept from a paper submission
  if (!complete(e)) return false;
  // a weight over 20 kg waits for the fix button, the server refuses it
  if (e.val === "kvar" && parseWeight(e.vikt).gramsHint !== null) return false;
  // a death before the birth or in the future waits too, the server refuses it
  if (e.val === "dod" && !deathDateOk(e.dod, r.birth_date)) return false;
  if (e.val === "kvar" && r.adult)
    return e.vikt.trim() !== "" || !!e.ej_vagd?.trim();
  return true;
}

function bodyEntry(e: Entry): BodyEntry | null {
  if (e.val === null || !complete(e)) return null;
  if (e.val === "kvar") {
    const w = e.ej_vagd?.trim() ? null : e.vikt.trim();
    return {
      val: "kvar",
      // plain kilos go as a number; anything else goes as typed, and the
      // server says vikt_ogiltig
      vikt: w ? (parseWeight(w).kg ?? w) : null,
      ej_vagd: e.ej_vagd?.trim() ? e.ej_vagd.trim() : null,
      hull: e.hull,
    };
  }
  if (e.val === "dod") {
    const d = e.dod!;
    return {
      val: "dod",
      dod: {
        ar: d.ar,
        manad: d.manad!,
        dag: d.dag,
        slaktad: d.slaktad,
        anteckning: d.anteckning,
      },
    };
  }
  if (e.val === "sald") {
    const s = e.sald!;
    return {
      val: "sald",
      sald: {
        till: s.till,
        ar: s.ar,
        manad: s.manad!,
        dag: s.dag,
        // Only a new sale outside the genebank carries the buyer. A saved
        // sale is sent without it (Task 6: unchanged unless filled in).
        ...(s.till === "utanfor" && s.kopare
          ? {
              kopare: {
                ...s.kopare,
                contact_consent: false as const,
                membership_optin: false as const,
              },
            }
          : {}),
      },
    };
  }
  return { val: "ej_angiven" };
}

export function toBody(
  state: FormState,
  key: string,
  revision: number | null,
): Submission {
  const rabbits: Record<string, BodyEntry> = {};
  for (const [id, e] of Object.entries(state.rabbits)) {
    const b = bodyEntry(e);
    if (b) rabbits[id] = b;
  }
  const diseases: DraftData["diseases"] = {};
  for (const { key: d } of DISEASES) {
    const s = state.diseases[d];
    if (!/^\d+$/.test(s.antal.trim())) continue;
    diseases[d] = {
      ...(d === "annat" ? { namn: s.namn.trim() || null } : {}),
      antal: Number(s.antal),
      alder: s.alder.trim() || null,
    };
  }
  return {
    submission_key: key,
    revision,
    reason: state.reason.trim() || null,
    rabbits,
    ending_genbank: state.ending,
    membership_after_end: state.ending ? state.membership : null,
    health: state.health,
    diseases: state.health === "ja" ? diseases : {},
    defects:
      state.health === "ja"
        ? state.defects.map((d) => ({
            individual_id: d.individual_id,
            beskrivning: d.beskrivning.trim() || null,
          }))
        : [],
    message: state.message.trim(),
  };
}

// Only these fields ever leave the form state or enter it from a stored draft:
// an unknown key (a matrikel, a buyer) is dropped, never copied on.
const isObj = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const num = (v: unknown): number | null => {
  const n =
    typeof v === "string" && v.trim() !== "" ? Number(v) : (v as number);
  return typeof n === "number" && Number.isFinite(n) ? n : null;
};
const str = (v: unknown): string => (typeof v === "string" ? v : "");
function pickEntry(raw: unknown): Entry {
  const e = (isObj(raw) ? raw : {}) as Partial<Entry>;
  const val = (["kvar", "dod", "sald", "ej_angiven"] as const).find(
    (v) => v === e.val,
  );
  const dod = isObj(e.dod) ? e.dod : null;
  const sald = isObj(e.sald) ? e.sald : null;
  return {
    val: val ?? null,
    vikt: str(e.vikt),
    ej_vagd: typeof e.ej_vagd === "string" ? e.ej_vagd : null,
    hull:
      (["low", "normal", "high"] as const).find((h) => h === e.hull) ?? null,
    dod: dod
      ? {
          ar: num(dod.ar) ?? 0,
          manad: num(dod.manad),
          dag: num(dod.dag),
          slaktad: !!dod.slaktad,
          anteckning: str(dod.anteckning),
        }
      : null,
    sald: sald
      ? {
          till: str(sald.till),
          ar: num(sald.ar) ?? 0,
          manad: num(sald.manad),
          dag: num(sald.dag),
          kopare: null,
        }
      : null,
  };
}
export function pickForm(raw: unknown): FormState {
  const f = (isObj(raw) ? raw : {}) as Partial<FormState>;
  const state = emptyState();
  for (const [id, e] of Object.entries(isObj(f.rabbits) ? f.rabbits : {}))
    state.rabbits[Number(id)] = pickEntry(e);
  for (const { key } of DISEASES) {
    const d = isObj(f.diseases) ? f.diseases[key] : null;
    if (isObj(d))
      state.diseases[key] = {
        antal: str(d.antal),
        alder: str(d.alder),
        namn: str(d.namn),
      };
  }
  state.defects = (Array.isArray(f.defects) ? f.defects : []).flatMap((d) =>
    !isObj(d) || num(d.individual_id) === null
      ? []
      : [
          {
            individual_id: d.individual_id as number,
            beskrivning: str(d.beskrivning),
          },
        ],
  );
  state.ending = !!f.ending;
  state.membership =
    f.membership === "kvar_utan_genbank" ||
    f.membership === "avsluta_medlemskap"
      ? f.membership
      : null;
  state.health = f.health === "inga" || f.health === "ja" ? f.health : null;
  state.message = str(f.message);
  state.reason = str(f.reason);
  return state;
}

// The draft is the body without the key, the revision and the buyers (D10).
export function toDraft(state: FormState): DraftData {
  const { submission_key, revision, ...draft } = toBody(state, "", null);
  void submission_key;
  void revision;
  for (const e of Object.values(draft.rabbits))
    if (e.sald) delete e.sald.kopare; // the buyer stays in memory
  const form = pickForm(state);
  for (const e of Object.values(form.rabbits))
    if (e.sald) delete (e.sald as { kopare?: unknown }).kopare; // memory only
  return { ...draft, form };
}

// A stored draft is data the server accepted as it was: it never throws. A
// malformed `form` falls back to the body shape, and that to an empty form.
export function fromBody(data: Partial<DraftData>): FormState {
  if (isObj(data?.form)) return pickForm(data.form);
  try {
    return fromShape(isObj(data) ? data : {});
  } catch {
    return emptyState();
  }
}

// The body shape (a draft the server wrote after Dra tillbaka, or
// report.submitted): rebuilt as a loose form and normalised by pickForm, so no
// field keeps a wrong type.
function fromShape(data: Partial<DraftData>): FormState {
  const rabbits: Record<string, unknown> = {};
  for (const [id, raw] of Object.entries(
    isObj(data.rabbits) ? data.rabbits : {},
  )) {
    const b: Record<string, unknown> = isObj(raw) ? raw : {};
    rabbits[id] = {
      val: b.val,
      vikt:
        b.val === "kvar" && typeof b.vikt === "number"
          ? kgText(b.vikt)
          : b.vikt,
      ej_vagd: b.val === "kvar" ? b.ej_vagd : null,
      hull: b.val === "kvar" ? b.hull : null,
      dod: b.val === "dod" ? b.dod : null,
      sald: b.val === "sald" ? b.sald : null,
    };
  }
  const diseases: Record<string, unknown> = {};
  for (const [d, v] of Object.entries(
    isObj(data.diseases) ? data.diseases : {},
  ))
    if (isObj(v))
      diseases[d] = {
        ...v,
        antal: typeof v.antal === "number" ? String(v.antal) : v.antal,
      };
  return pickForm({
    rabbits,
    ending: data.ending_genbank,
    membership: data.membership_after_end,
    health: data.health,
    diseases,
    defects: data.defects,
    message: data.message,
    reason: (data as { reason?: unknown }).reason,
  } as unknown as Partial<FormState>);
}

const STOCKHOLM = "Europe/Stockholm";
export const fmtDate = (iso: string): string =>
  new Intl.DateTimeFormat("sv-SE", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: iso.length > 10 ? STOCKHOLM : "UTC",
  }).format(new Date(iso));
// Today's calendar date in Stockholm, "YYYY-MM-DD" (sv-SE formats that way).
export const todayStockholm = (): string =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: STOCKHOLM }).format(new Date());
export const fmtTime = (iso: string): string =>
  new Intl.DateTimeFormat("sv-SE", {
    hour: "2-digit",
    minute: "2-digit",
    timeZone: STOCKHOLM,
  })
    .format(new Date(iso))
    .replace(":", ".");

export function ageText(r: RabbitView, year: number): string | null {
  if (!r.birth_date) return null;
  const years = year - Number(r.birth_date.slice(0, 4));
  return years < 1 ? "född " + r.birth_date.slice(0, 4) : `${years} år`;
}

export const sexText = (r: RabbitView) =>
  r.sex === "female" ? "Hona" : r.sex === "male" ? "Hane" : "Okänt kön";

// Calendar date of a timestamp in Stockholm, "YYYY-MM-DD".
export const stockholmDay = (iso: string): string =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: STOCKHOLM }).format(
    new Date(iso),
  );

// ---- Paper entry (Task 14) --------------------------------------------------

// What the paper form's contact part holds while it is typed. It lives apart
// from FormState, so it can never reach a draft or localStorage.
export interface PaperFields {
  adress: { address: string; postal_code: string; city: string };
  telefon: string;
  epost: string;
  konto: { clearing: string; konto: string; bank: string };
  consent: "" | "ja" | "nej";
  utom: Utom[];
}

export const emptyPaperFields = (): PaperFields => ({
  adress: { address: "", postal_code: "", city: "" },
  telefon: "",
  epost: "",
  konto: { clearing: "", konto: "", bank: "" },
  consent: "",
  utom: [],
});

// Only the filled fields go, and nothing at all (null) when none is filled: the
// server then takes no lock on the matrikel. An empty consent is no answer.
export function matrikelBody(f: PaperFields): Submission["matrikel"] | null {
  const filled = (o: Record<string, string>) =>
    Object.fromEntries(
      Object.entries(o)
        .map(([k, v]) => [k, v.trim()])
        .filter(([, v]) => v),
    );
  const body: Matrikel = {};
  const adress = filled(f.adress);
  if (Object.keys(adress).length) body.adress = adress;
  if (f.telefon.trim()) body.telefon = f.telefon.trim();
  if (f.epost.trim()) body.epost = f.epost.trim();
  const konto = filled(f.konto);
  if (Object.keys(konto).length) body.konto = konto;
  if (f.consent)
    body.publicering = {
      ja: f.consent === "ja",
      utom: f.consent === "ja" ? f.utom : [],
    };
  return Object.keys(body).length ? body : null;
}

// The arsblankett pages of a queue item that are not done (no done_at: a
// document is "klar" or "avfardad" exactly when done_at is set). Archiving
// dismisses these and leaves the item's other documents alone.
export const formDocumentIds = (item: InboxDetail): number[] =>
  item.documents
    .filter(
      (d) =>
        d.doc_type === "arsblankett" &&
        d.status !== "klar" &&
        d.status !== "avfardad",
    )
    .map((d) => d.id);

// 5.8: the item's other documents (intyg, bevis) come before the form. One that
// is not done, or waits for a parent, holds the form back.
export const intygPending = (item: InboxDetail): boolean =>
  item.documents.some(
    (d) =>
      d.doc_type !== "arsblankett" &&
      (!["klar", "avfardad"].includes(d.status) || !!d.waiting_for?.length),
  );

// The keyboard chain of one rabbit's row (design brief 4): where the focus is
// and what is chosen, and what a key does. Digits never choose in a text field.
export type PaperField =
  | "number"
  | "val"
  | "vikt"
  | "ej_vagd"
  | "hull"
  | "month"
  | "day"
  | "slaktad"
  | "note"
  | "sold";
export interface PaperState {
  field: PaperField;
  val: Val | null;
}
const VAL_KEYS: Record<string, Val> = { "1": "kvar", "2": "dod", "3": "sald" };
const AFTER_VAL: Record<string, PaperField> = {
  kvar: "vikt",
  dod: "month",
  sald: "sold",
};
export function paperKey(state: PaperState, key: string): PaperState {
  const { field } = state;
  if (field === "val" && key in VAL_KEYS) {
    const val = VAL_KEYS[key];
    return { field: AFTER_VAL[val], val };
  }
  if (key === "Enter" || key === "Tab") {
    if (field === "number" && key === "Enter")
      return { ...state, field: "val" };
    if (field === "vikt") return { ...state, field: "ej_vagd" };
    if (field === "ej_vagd") return { ...state, field: "hull" };
    // a dead rabbit: month, day, Slaktad, Anteckning, then the next row
    if (key === "Enter" && field === "month") return { ...state, field: "day" };
    if (key === "Enter" && field === "day")
      return { ...state, field: "slaktad" };
    if (key === "Enter" && field === "slaktad")
      return { ...state, field: "note" };
    // the last field of a row: Enter starts the next row
    if (key === "Enter" && ["hull", "note", "sold"].includes(field))
      return { ...state, field: "number" };
  }
  return state;
}

// ---- Status view (Task 15) --------------------------------------------------

export type RowState =
  | "avslutar"
  | "inskickad"
  | "blankett_vantar"
  | "blankett_inkommen"
  | "paborjad"
  | "ingen_epost"
  | "ej_rapporterad";

export const ROW_STATES: RowState[] = [
  "paborjad",
  "ej_rapporterad",
  "ingen_epost",
  "blankett_inkommen",
  "blankett_vantar",
  "inskickad",
  "avslutar",
];

export const ROW_STATE_TEXT: Record<RowState, string> = {
  avslutar: "Avslutar",
  inskickad: "Inskickad",
  blankett_vantar: "Blankett väntar på svar",
  blankett_inkommen: "Blankett inkommen",
  paborjad: "Påbörjad",
  ingen_epost: "Ingen e-post",
  ej_rapporterad: "Ej rapporterad",
};

// The filter labels use the plural ("Påbörjade 12").
export const ROW_STATE_FILTER: Record<RowState, string> = {
  avslutar: "Avslutar",
  inskickad: "Inskickade",
  blankett_vantar: "Blankett väntar på svar",
  blankett_inkommen: "Blankett inkommen",
  paborjad: "Påbörjade",
  ingen_epost: "Ingen e-post",
  ej_rapporterad: "Ej rapporterade",
};

// The invitation's state, from the mail queue and the link (spec 5.14).
export type Invitation = "skickad" | "studsade" | "misslyckades" | "oppnad";

export const INVITATION_TEXT: Record<Invitation, string> = {
  skickad: "Inbjudan skickad",
  studsade: "Inbjudan studsade",
  misslyckades: "Inbjudan misslyckades",
  oppnad: "Länken öppnad",
};

export interface StatusRow {
  herd: string;
  herd_name: string | null;
  state: RowState;
  inbjudan: Invitation | null;
  ingen_epost: boolean;
  source: "login" | "link" | "paper" | null;
  membership_after_end: Membership | null;
  received_at: string | null;
  on_time_override: boolean | null;
  inbox_item_id: number | null;
  telefon?: string | null; // only for genebank managers
  flags: { ej_angivna: number; ej_angivna_paverkar: boolean };
  villkor: Villkor;
  statistik: {
    kullar: number;
    ungar: number;
    levande_6v: number;
    honor: number;
    hanar: number;
  };
}

export interface RoundGenebank {
  genebank_id: number;
  activated_at: string;
  activated_by: { id: number; name: string };
  send_at: string | null;
  sent_at: string | null;
}

export interface Round {
  year: number;
  start_date: string | null;
  deadline: string | null;
  end_date: string | null;
  is_active: boolean;
  genebanks: RoundGenebank[];
}

export interface StatusView {
  round: Round;
  genebank_id: number;
  activated: boolean;
  counts: Record<RowState, number>;
  rows: StatusRow[];
}

export type StatusFilter = "att_ringa" | "alla" | RowState;

export const parseFilter = (v: string | undefined): StatusFilter =>
  v === "att_ringa" || ROW_STATES.includes(v as RowState)
    ? (v as StatusFilter)
    : "alla";

// Calendar arithmetic on "YYYY-MM-DD" in UTC, so no daylight-saving hour moves a date.
export const callFrom = (deadline: string): string =>
  new Date(Date.parse(`${deadline.slice(0, 10)}T00:00:00Z`) - 2 * 86_400_000)
    .toISOString()
    .slice(0, 10);

// Spec 5.14: a herd with a draft is phoned from two days before the round's
// deadline; a herd whose form left out rabbits that decide the support at any
// time; a herd whose invitation bounced or failed, until it has reported.

export function toCall(
  row: StatusRow,
  deadline: string | null,
  today: string,
): boolean {
  if (row.flags.ej_angivna_paverkar) return true;
  if (
    (row.inbjudan === "studsade" || row.inbjudan === "misslyckades") &&
    row.state !== "inskickad" &&
    row.state !== "avslutar" // a report has come in either way
  )
    return true;
  return (
    deadline !== null && row.state === "paborjad" && today >= callFrom(deadline)
  );
}

export function filterRows(
  rows: StatusRow[],
  filter: StatusFilter,
  deadline: string | null,
  today: string = todayStockholm(),
): StatusRow[] {
  if (filter === "alla") return rows;
  if (filter === "att_ringa")
    return rows.filter((r) => toCall(r, deadline, today));
  return rows.filter((r) => r.state === filter);
}

export function countByState(rows: StatusRow[]): Record<RowState, number> {
  const counts = Object.fromEntries(ROW_STATES.map((s) => [s, 0])) as Record<
    RowState,
    number
  >;
  for (const r of rows) counts[r.state] += 1;
  return counts;
}

// Autosave and Skicka. A save may leave only while no submission is in flight
// (the caller checks), and its answer counts only when no submission has
// started since it left: submissions is a counter that Skicka raises.
export const autosaveAnswerKept = (
  sentAt: number,
  submissionsNow: number,
): boolean => sentAt === submissionsNow;
