// Shapes of /api/v2/arsrapport/* and the form's own logic. Kept free of React
// and of server actions so the paper page (Task 14) and the status view
// (Task 15) can reuse it.

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

export interface Submission extends DraftData {
  submission_key: string;
  revision: number | null;
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
  access: "owner" | "caretaker" | "manager" | "admin" | "helper";
  source: "login" | "paper";
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
// (CONSENT_TEXT_VERSION "2026-11" on the server). Only the paper form shows it.
export const CONSENT_TEXT =
  "Får din genbank stå med i listan över aktiva genbanker i Koharen? Listan gör det lättare för genbankerna att hitta varandra. Den visar innehavarens namn och genbankens nummer, och dessutom postnummer och ort, telefonnummer och e-postadress ur medlemsregistret.";

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
  inte_klar: "Välj Finns kvar, Död eller slaktad eller Såld.",
  vikt_saknas: "Vuxna kaniner behöver vikt eller Ej vägd.",
  vikt_ogiltig: "Ange vikten i kilo, till exempel 2,8.",
  rundan_stangd:
    "Rundan är stängd. Kontakta genbanksansvarig om något behöver ändras.",
  inte_innehavare: "Kaninen fanns inte i din besättning 31 december.",
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
};
export const CONFLICT_TEXT = "Rapporten har ändrats på en annan enhet";
export const TIMEOUT_TEXT =
  "Vi vet inte om rapporten kom fram. Tryck Försök igen. Den skickas inte två gånger.";

export const refusalText = (r: Refusal) => REFUSAL_TEXT[r.code] ?? r.message;

export function newKey(): string {
  return crypto.randomUUID();
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

// "2,8" and "2.8" are kilos; above 100 the user probably typed grams.
export function parseWeight(text: string): {
  kg: number | null;
  gramsHint: number | null;
  unusual: boolean;
} {
  const t = text.trim().replace(",", ".");
  if (!/^\d+(\.\d+)?$/.test(t))
    return { kg: null, gramsHint: null, unusual: false };
  const n = Number(t);
  if (n > 100)
    return {
      kg: null,
      gramsHint: Number((n / 1000).toFixed(3)),
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

export function isDone(
  r: RabbitView,
  e: Entry | undefined,
  ending: boolean,
): boolean {
  if (ending) return true; // 5.7: an ending genebank needs neither choice nor weight
  if (!e || e.val === null) return r.state !== "att_valja";
  if (e.val === "ej_angiven") return true; // P44: kept from a paper submission
  if (!complete(e)) return false;
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
const num = (v: unknown): number | null =>
  typeof v === "number" && Number.isFinite(v) ? v : null;
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

function fromEntry(b: Partial<BodyEntry> & { val?: Val | null }): Entry {
  const val = b.val ?? null;
  return {
    val,
    vikt:
      val === "kvar" && b.vikt != null && b.vikt !== ""
        ? typeof b.vikt === "number"
          ? kgText(b.vikt)
          : String(b.vikt)
        : "",
    ej_vagd: val === "kvar" ? (b.ej_vagd ?? null) : null,
    hull: val === "kvar" ? (b.hull ?? null) : null,
    dod:
      val === "dod" && b.dod
        ? {
            ar: b.dod.ar,
            manad: b.dod.manad,
            dag: b.dod.dag ?? null,
            slaktad: !!b.dod.slaktad,
            anteckning: b.dod.anteckning ?? "",
          }
        : null,
    sald:
      val === "sald" && b.sald
        ? {
            till: b.sald.till,
            ar: b.sald.ar,
            manad: b.sald.manad,
            dag: b.sald.dag ?? null,
            kopare: null,
          }
        : null,
  };
}

// A draft, or report.submitted, back into the form. The buyers are gone.
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

function fromShape(data: Partial<DraftData>): FormState {
  const state = emptyState();
  for (const [id, raw] of Object.entries(data.rabbits ?? {}))
    state.rabbits[Number(id)] = fromEntry(raw);
  state.ending = !!data.ending_genbank;
  state.membership = data.membership_after_end ?? null;
  state.health = data.health ?? null;
  for (const [d, v] of Object.entries(data.diseases ?? {})) {
    state.diseases[d as Disease] = {
      antal: String(v.antal),
      alder: v.alder ?? "",
      namn: (v as { namn?: string | null }).namn ?? "",
    };
  }
  state.defects = (data.defects ?? []).map((d) => ({
    individual_id: d.individual_id,
    beskrivning: d.beskrivning ?? "",
  }));
  state.message = data.message ?? "";
  state.reason = (data as { reason?: string | null }).reason ?? "";
  return state;
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
