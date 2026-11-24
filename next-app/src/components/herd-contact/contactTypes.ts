export type Privacy = "private" | "authenticated" | "public";
/** a stored level as the server reads it: NULL and an unknown value ("Public ") are private */
export const privacyOf = (p: string | null | undefined): Privacy =>
  p === "authenticated" || p === "public" ? p : "private";
export type ContactField =
  | "name"
  | "email"
  | "mobile_phone"
  | "physical_address";

export interface ContactPerson {
  id: number;
  name: string;
  role: string;
}

export interface ReaderRow {
  // GET reports a fetched row as "person" (name, e-post, mobil) or "medlemskap" (adress);
  // the PATCH echoes it back unchanged in `shown`.
  source: "egen" | "person" | "medlemskap";
  privacy: Privacy;
  pending: boolean;
  alternative: string | null;
}

/** `contact` for a matrikel reader (household, genebank manager, admin). */
export interface ReaderContact {
  mode: "ej_jamford" | "person" | "fritext" | "ingen";
  contact_member: ContactPerson | null;
  rows: Record<ContactField, ReaderRow>;
  persons?: ContactPerson[];
}

export type OwnerRow =
  | { source: "egen"; value: string | null; privacy: Privacy }
  | { source: "hamtad" };

/** `contact` for private access without register access: no values from the register. */
export interface OwnerContact {
  rows: Partial<Record<ContactField, OwnerRow>>;
}

export type Contact = ReaderContact | OwnerContact;

export const isReader = (c: Contact): c is ReaderContact => "mode" in c;

/** The herd's flat fields as the GET returns them (resolved values). */
export type HerdFields = Record<string, any>;

export type SaveResult =
  | { success: true; data?: unknown }
  | { success: false; error: string; status?: number; type?: string };

export type OnSave = (patch: {
  contact: Record<string, unknown>;
}) => Promise<SaveResult>;

export const FIELD_LABEL: Record<ContactField, string> = {
  name: "Kontaktperson",
  email: "E-post",
  mobile_phone: "Mobil",
  physical_address: "Adress",
};

export const PRIVACY_LABEL: Record<string, string> = {
  authenticated: "Inloggade besättningar",
  private: "Endast genbanksansvarig",
  public: "Synligt för alla",
};

export const ROLE_LABEL: Record<string, string> = {
  huvudmedlem: "huvudmedlem",
  familjemedlem: "familjemedlem",
  skotare: "skötare",
};

export const roleLabel = (role: string) => ROLE_LABEL[role] ?? role;

export const isFetched = (source: string) =>
  source === "person" || source === "medlemskap";

/** `gata|postnr|ort`, or a bare street without "|". */
export function splitAddress(raw: string | null | undefined) {
  const [street = "", postal = "", city = ""] = (raw ?? "").split("|");
  return { street, postal, city };
}

export function joinAddress(street: string, postal: string, city: string) {
  // a bare street stays bare, so a stored address without "|" is never rewritten
  return !postal && !city ? street : `${street}|${postal}|${city}`;
}

export function formatAddress(raw: string): [string, string] {
  const { street, postal, city } = splitAddress(raw);
  return [street, `${postal} ${city}`.trim()];
}

export const firstName = (name: string) => name.split(" ")[0];

const ASK_NOUN: Record<ContactField, [string, string]> = {
  name: ["Namnet", "namnet"],
  email: ["E-postadressen", "adressen"],
  mobile_phone: ["Mobilnumret", "numret"],
  physical_address: ["Adressen", "adressen"],
};
export const askText = (field: ContactField) => ASK_NOUN[field];

/** What the form showed of one row, for the server's check against the stored state. */
export const shownRow = (
  field: ContactField,
  row: ReaderRow,
  herd: HerdFields,
) => ({
  source: row.source,
  value: herd[field] ?? null,
  alternative: row.alternative,
  privacy: row.privacy,
});

/** What the form showed of the contact person: mode, person id, and the own name of a contact outside the register. */
export const shownTop = (contact: ReaderContact, herd: HerdFields) => ({
  mode: contact.mode,
  contact_member: contact.contact_member?.id ?? null,
  name: contact.mode === "fritext" ? (herd.name ?? null) : null,
});

export const isConflict = (r: SaveResult) =>
  !r.success && r.status === 409 && r.type === "contact-changed";

export const CONFLICT_TEXT =
  "Uppgifterna har ändrats sedan sidan öppnades. Formuläret är omläst, så kontrollera och försök igen.";
