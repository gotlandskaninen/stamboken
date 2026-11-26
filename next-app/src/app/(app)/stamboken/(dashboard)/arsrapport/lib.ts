// Shapes of /api/v2/arsrapport/* and the form's own logic. Kept free of React
// and of server actions so the paper page (Task 14) and the status view
// (Task 15) can reuse it.
import type { SaleBuyer } from "@/components/individual/BuyerFields";
import { newOperationId } from "@/lib/herdTracking";
import type { Mode } from "@/lib/mode";
import type { InboxDetail } from "../inkorg/lib";

export const BEVIS_FROM_YEAR = 2027;

export function reportLinkPath(path: string) {
  return `${path}${path.includes("?") ? "&" : "?"}via=lank`;
}

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
  death_day_known: boolean; // false: the report gave it without its day, so its month is shown
  state: "att_valja" | "redan_rapporterad" | "via_flytt";
  later: { kind: string; date: string } | null;
  buyer_removed?: boolean;
  removed_buyer_dates?: string[];
  registered_buyer_date?: string;
  kept_buyer_date?: string;
  // The latest transfer into the herd dated in the year: "Köpt 14 maj" (4a Task 5).
  kopt: { datum: string; fran: string | null } | null;
}

// A purchase notice the herd sent ("Anmäl köpet"): a queue item for the
// genebank manager until the transfer is registered.
// "Anmäl köpet" (4a Task 5): the body of …/kop.
export interface PurchaseBody {
  number: string;
  from_herd: string; // a herd's number, or "utanfor"
  date: string;
  document_id?: number; // a photo this session uploaded through …/foto, and what it shows
  doc_type?: "bevis" | "intyg";
}

export interface PurchaseNotice {
  id: number;
  number: string;
  from_herd: string;
  date: string;
  state: string;
}

// "Skicka till genbanksansvarig" (S7): the body of …/kop/inskick, a rabbit
// Stamboken lacks, with the photos this session uploaded with syfte=inskick.
export interface PurchasePhotosBody {
  number: string;
  from_herd: string;
  date: string;
  documents: { id: number; doc_type: "bevis" | "intyg" }[];
}

// "Ärenden hos genbanksansvarig" (S8): one queue item that concerns the report.
export interface ReportCase {
  id: number;
  what: "inskick" | "kop_saknas" | "kopanmalan" | "foto" | "forsaljning";
  number: string | null;
  photos: number;
  state: "tolkas" | "vantar" | "arbetar" | "registrerad" | "klart";
}

export const CASE_STATE_TEXT: Record<ReportCase["state"], string> = {
  tolkas: "Väntar på att fotot läses",
  vantar: "Väntar på genbanksansvarig",
  arbetar: "Genbanksansvarig arbetar med det",
  registrerad: "Registrerad, genbanksansvarig avslutar ärendet",
  klart: "Klart",
};

export function caseText(c: ReportCase): string {
  const n = c.number ?? "";
  if (c.what === "kop_saknas") return `Köpt kanin finns inte i registret: ${n}`;
  if (c.what === "kopanmalan") return `Anmält köp: ${n}`;
  if (c.what === "foto") return n ? `Foto av intyget: ${n}` : "Foto av intyget";
  if (c.what === "forsaljning") return `Försäljning av ${n}`;
  return `Inskick med ${c.photos} ${c.photos === 1 ? "foto" : "foton"}`;
}

// "Kullar under Y": one litter of the herd; `preliminary` while the 6-week count is still the count born.
export interface Litter {
  id: number;
  litter_number: number | null;
  birth_date: string;
  mother: string | null;
  father: string | null;
  litter_size: number | null;
  litter_size6w: number | null;
  preliminary: boolean;
}

// POST kull; an empty litter_size6w is a preliminary count.
export interface LitterBody {
  mother_id: number;
  father_id: number;
  birth_date: string;
  litter_size: number;
  litter_size6w: number | null;
}

// A father of the picker: the genebank's living males, and nothing else about them.
export interface Father {
  id: number;
  number: string;
  name: string | null;
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
  vantar?: number; // of salda, those sent as proposals (5.9)
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
// The API takes what is left out; the form asks what may appear, none ticked at first.
export const UTOM_ALL: Utom[] = ["phone", "email", "address"];
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
  litters: Litter[];
  sales: {
    individual_id: number;
    number: string;
    to_herd: string;
    date: string;
    day_known: boolean; // false: the report gave it without its day (5.3), so its month is shown
  }[];
  // The report's sale proposals not taken back (5.9), without the buyer.
  forslag: {
    individual_id: number;
    to_herd: string | null;
    sale_date: string;
    state: "foreslagen" | "godkand" | "avvisad";
  }[];
  // The herd's purchase notices dated in the year.
  kopanmalningar: PurchaseNotice[];
  arenden: ReportCase[];
  herds: string[];
  report: null | {
    id: number;
    status: string;
    source: string;
    revision: number;
    received_at: string;
    report_date: string;
    on_time: boolean;
    submitted: (Partial<DraftData> & { received_on?: string }) | null;
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
// in localStorage (D10). The contact details only with the buyer's yes
// (BuyerFields, ADR-0016).
export type Buyer = SaleBuyer;
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
  // A buyer kept across Dra tillbaka (K1): the server's id, carried untouched.
  kopare_id?: number;
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
    kopare?: Buyer;
    kopare_id?: number;
  };
}

export const SUBMIT_TIMEOUT_MS = 30_000;

// The wording of the blankett's question about the listing in Koharen
// (CONSENT_TEXT_VERSION "2026-11-20" on the server). Only the paper form shows it.
export const CONSENT_TEXT =
  "Får din besättning stå med i Koharens lista över aktiva besättningar? Koharen är föreningens tidning på papper och går bara till medlemmar. Listan gör det lättare för besättningarna att hitta varandra.";

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
  kopare_saknas: "Fyll i köparen, eller välj såld utanför genbanken.",
  halsa_saknas: "Välj Inga sjukdomsfall eller defekter, eller Ja.",
  ej_angiven_digitalt: "Ej angiven finns bara när en blankett matas in.",
  orsak_kravs: "Skriv varför rapporten ändras.",
  orsak_kopare: "Skriv inte köparens namn i orsaken.",
};
export const CONFLICT_TEXT = "Rapporten har ändrats på en annan enhet";
// A sale by a caretaker or through the link is a proposal (5.9).
export const PENDING_SALE_TEXT =
  "Försäljningen väntar på genbanksansvarig. Kaninen står kvar hos dig tills den är godkänd.";
export const PURCHASE_SENT_TEXT =
  "Anmälan är skickad till genbanksansvarig. Kaninen kommer in i din besättning när köpet är registrerat.";
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

// K1, FB6: the server deletes a kept buyer once its row is no longer a sale
// outside the genebank, so the row lets go of the id too.
export function withoutGoneBuyer(e: Entry): Entry {
  if (e.sald?.kopare_id == null) return e;
  if (e.val === "sald" && e.sald.till === "utanfor") return e;
  const { kopare_id, ...sald } = e.sald;
  void kopare_id;
  return { ...e, sald };
}

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
  const iso = eventDate(d, today)!;
  return iso <= today && (!birth || iso >= birth.slice(0, 10));
}

export function eventDate(
  d: Pick<SaldState, "ar" | "manad" | "dag">,
  today = todayStockholm(),
): string | null {
  if (d.manad === null) return null;
  const day = d.dag ?? new Date(Date.UTC(d.ar, d.manad, 0)).getUTCDate();
  const iso = `${d.ar}-${String(d.manad).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
  return d.dag === null && iso > today ? today : iso;
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

// The sale outside the genebank that the report's latest submission holds,
// unchanged: its buyer is stored, so it needs none typed again.
export const storedSale = (
  s: Pick<SaldState, "till" | "ar" | "manad" | "dag">,
  submitted: BodyEntry["sald"] | null | undefined,
): boolean =>
  s.till === "utanfor" &&
  submitted?.till === "utanfor" &&
  submitted.ar === s.ar &&
  submitted.manad === s.manad &&
  (submitted.dag ?? null) === s.dag;

export function buyerRemoved(
  rabbit: Pick<RabbitView, "buyer_removed" | "removed_buyer_dates"> | undefined,
  sale: Pick<SaldState, "ar" | "manad" | "dag">,
): boolean {
  return !!(
    rabbit?.buyer_removed ||
    rabbit?.removed_buyer_dates?.some((date) => {
      const [year, month, day] = date.split("-").map(Number);
      return (
        year === sale.ar &&
        month === sale.manad &&
        (sale.dag === null || day === sale.dag)
      );
    })
  );
}

// A sale outside the genebank that Skicka would refuse for its buyer
// (kopare_saknas): none typed, not the stored sale, and no kept buyer the role
// may use (K1). The draft never holds a buyer, so a sale only in the draft
// needs it again.
export const lacksBuyer = (
  s: SaldState,
  submitted: BodyEntry["sald"] | null | undefined,
  canSell: boolean,
  rabbit: RabbitView,
): boolean =>
  s.till === "utanfor" &&
  !s.kopare &&
  !buyerRemoved(rabbit, s) &&
  !(
    canSell &&
    s.kopare_id != null &&
    eventDate(s) === rabbit.kept_buyer_date
  ) &&
  !storedSale(s, submitted);

export function isDone(
  r: RabbitView,
  e: Entry | undefined,
  ending: boolean,
  submitted?: BodyEntry["sald"] | null, // the rabbit's sale in report.submitted
  canSell = true,
): boolean {
  if (ending) return true; // 5.7: an ending genebank needs neither choice nor weight
  if (!e || e.val === null) return r.state !== "att_valja";
  if (e.val === "ej_angiven") return true; // P44: kept from a paper submission
  if (!complete(e)) return false;
  if (e.val === "sald" && lacksBuyer(e.sald!, submitted, canSell, r))
    return false;
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
        // sale is sent without it (Task 6: unchanged unless filled in), and a
        // kept one with its id (K1).
        ...(s.till === "utanfor" && s.kopare ? { kopare: s.kopare } : {}),
        ...(s.till === "utanfor" && s.kopare_id != null
          ? { kopare_id: s.kopare_id }
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
  // Skicka sends only the rabbits on the current list: a sold one may linger in a local copy (FB1)
  listed?: readonly number[],
): Submission {
  const rabbits: Record<string, BodyEntry> = {};
  for (const [id, e] of Object.entries(state.rabbits)) {
    if (listed && !listed.includes(Number(id))) continue;
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
        ? state.defects
            .filter((d) => !listed || listed.includes(d.individual_id))
            .map((d) => ({
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
          ...(num(sald.kopare_id) !== null
            ? { kopare_id: num(sald.kopare_id)! }
            : {}),
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
// "14 maj": the bought mark on a rabbit's row.
export const fmtDay = (iso: string): string =>
  new Intl.DateTimeFormat("sv-SE", {
    day: "numeric",
    month: "long",
    timeZone: "UTC",
  }).format(new Date(iso));
export const fmtDate = (iso: string): string =>
  new Intl.DateTimeFormat("sv-SE", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: iso.length > 10 ? STOCKHOLM : "UTC",
  }).format(new Date(iso));
// A sale or death given without its day has a made-up one in the register (5.3): its month only, "maj 2025".
export const fmtDayOrMonth = (iso: string, dayKnown: boolean): string =>
  dayKnown
    ? fmtDate(iso)
    : new Intl.DateTimeFormat("sv-SE", {
        month: "long",
        year: "numeric",
        timeZone: "UTC",
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
  needs_report: boolean; // active herd without a submitted report this round
  inbjudan: Invitation | null;
  // The herd's latest reminder in the mail queue.
  last_reminder: {
    queued_at: string;
    sent_at: string | null;
    status: string;
  } | null;
  ingen_epost: boolean;
  source: "login" | "link" | "paper" | null;
  membership_after_end: Membership | null;
  received_at: string | null;
  on_time_override: boolean | null;
  inbox_item_id: number | null;
  telefon?: string | null; // only for genebank managers
  flags: {
    ej_angivna: number;
    ej_angivna_paverkar: boolean;
    forsaljning_vantar: number; // pending sale proposals (5.9)
    forsaljning_avvisad: number; // rabbits a rejected sale left to choose again (FB3)
    forsaljning_avvisad_paverkar: boolean;
    kopt_efter_inskick: number; // sales into the herd approved after its report (FB4)
    kop_anmalt: number; // the herd's open purchase notices that no pending sale matches (4a Task 5)
  };
  villkor: Villkor;
  statistik: {
    kullar: number;
    ungar: number;
    levande_6v: number;
    preliminart?: boolean; // a litter's 6-week count is still a guess
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

// Fråga 7: the server's defaults for a new round (arsrapport.default_dates).
export const defaultRoundDates = (year: number) => ({
  start_date: `${year}-12-31`,
  deadline: `${year + 1}-01-31`,
  end_date: `${year + 1}-03-30`,
});

// The year being reported now, whether or not its round exists: last year's until that round (or its default)
// closes, then this year's.
export function regularRoundYear(rounds: Round[], today: string): number {
  const year = Number(today.slice(0, 4));
  const last = rounds.find((r) => r.year === year - 1);
  const lastEnd = last?.end_date ?? defaultRoundDates(year - 1).end_date;
  return today <= lastEnd ? year - 1 : year;
}

// The round managers work on: the oldest one open today (a round prepared for later does not count), else the
// regular year's.
export function currentRoundYear(rounds: Round[], today: string): number {
  const open = rounds
    .filter(
      (r) =>
        r.start_date &&
        r.end_date &&
        r.start_date <= today &&
        today <= r.end_date,
    )
    .map((r) => r.year);
  return open.length > 0 ? Math.min(...open) : regularRoundYear(rounds, today);
}

// A phone field can hold two numbers, "08 - 510 122 07 0709 - 55 72 08": split before each piece that starts like
// a number of its own ("0NN - ", "+NN - "). From the right, a piece with fewer than the seven digits of a whole
// number joins the one before it ("070-123 04-56"), and a short first piece joins the next ("Mobil 070-…").
const digits = (s: string) => s.replace(/\D/g, "").length;
export function phoneNumbers(text: string): string[] {
  const pieces = text
    .trim()
    .split(/\s+(?=(?:\+|0)\d*\s*-\s*\d)/)
    .filter(Boolean);
  const numbers: string[] = [];
  for (const piece of pieces.reverse()) {
    if (numbers.length > 0 && digits(numbers[0]) < 7)
      numbers[0] = `${piece} ${numbers[0]}`;
    else numbers.unshift(piece);
  }
  if (numbers.length > 1 && digits(numbers[0]) < 7)
    numbers.splice(0, 2, `${numbers[0]} ${numbers[1]}`);
  return numbers;
}

export interface StatusView {
  round: Round;
  genebank_id: number;
  activated: boolean;
  counts: Record<RowState, number>;
  rows: StatusRow[];
}

// The status view's sale dialog (5.9): a pending proposal, a buyer outside
// the genebank by name and town only.
export interface SaleProposalRow {
  id: number;
  individual_id: number;
  number: string;
  name: string | null;
  to_herd: string | null;
  buyer: { name: string; town: string | null } | null;
  buyer_not_recorded: boolean; // såld utanför genbanken: no buyer kept (#273)
  sale_date: string;
  day_known: boolean; // false: the report gave it without its day (5.3), so its month is shown
  buyer_notified_at: string | null; // the buyer's own notice (K7)
  kopanmalan: PurchaseNotice | null; // the buyer herd's notice that approving settles (fråga 19)
  kopanmalan_avviker: PurchaseNotice | null; // its notice dated too far off or across 31/12 (M1)
}

export type StatusFilter = "att_ringa" | "ej_svarat" | "alla" | RowState;

export const parseFilter = (v: string | undefined): StatusFilter =>
  v === "att_ringa" || v === "ej_svarat" || ROW_STATES.includes(v as RowState)
    ? (v as StatusFilter)
    : "alla";

// Calendar arithmetic on "YYYY-MM-DD" in UTC, so no daylight-saving hour moves a date.
export const callFrom = (deadline: string): string =>
  new Date(Date.parse(`${deadline.slice(0, 10)}T00:00:00Z`) - 2 * 86_400_000)
    .toISOString()
    .slice(0, 10);

// Spec 5.14: a herd with a draft is phoned from two days before the round's
// deadline; a herd whose form left out rabbits that decide the support, or
// whose rejected sale left such a rabbit to choose again (FB3), at any time; a
// herd whose invitation bounced or failed, until it has reported.

export function toCall(
  row: StatusRow,
  deadline: string | null,
  today: string,
): boolean {
  if (row.flags.ej_angivna_paverkar || row.flags.forsaljning_avvisad_paverkar)
    return true;
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
  if (filter === "ej_svarat") return rows.filter((r) => r.needs_report);
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
