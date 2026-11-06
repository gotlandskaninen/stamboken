// Svenska etiketter för audit-datats råa DB-termer.
// Okända värden faller tillbaka på råsträngen.
// Nycklarna täcker alla 12 tabeller i AUDITED_TABLES
// (app/utils/database.py:2434-2451) + audit_log (som bara REDACT-rader rör).
export const TABLE_LABELS: Record<string, string> = {
  individual: "Kaniner",
  breeding: "Parningar",
  bunny: "Ungar",
  herd: "Besättningar",
  herd_tracking: "Besättningshistorik",
  weight: "Viktmätningar",
  bodyfat: "Hullmätningar",
  individualdisease: "Sjukdomsnoteringar",
  color: "Färger",
  hbuser: "Användare",
  genebank: "Genbanker",
  authenticators: "Inloggningsmetoder",
  audit_log: "Aktivitetslogg",
};

export const OPERATION_LABELS: Record<string, string> = {
  INSERT: "Skapad",
  UPDATE: "Ändrad",
  DELETE: "Borttagen",
  SYSTEM: "Systemhändelse",
  REDACT: "Gallring",
};

// "Skapad av admin" / "Ändrad av admin" — läsbar fras i radhuvudet.
const OPERATION_PREPOSITION: Record<string, string> = {
  INSERT: "Skapad av",
  UPDATE: "Ändrad av",
  DELETE: "Borttagen av",
  SYSTEM: "Utförd av",
  REDACT: "Utförd av",
};

export const tableLabel = (t: string) => TABLE_LABELS[t] ?? t;
export const operationLabel = (op: string) => OPERATION_LABELS[op] ?? op;
export const operationPhrase = (op: string, by: string) =>
  `${OPERATION_PREPOSITION[op] ?? `${op} av`} ${by}`;

// Systemhändelser skriver markörrader med konstruerade record_id:n
// (t.ex. "mass-logout-<utc>") — visa en begriplig titel i stället för
// "Användare #mass-logout-…".
export function rowTitle(tableName: string, recordId: string): string {
  if (recordId.startsWith("mass-logout-")) {
    return "Massutloggning — alla sessioner";
  }
  if (recordId.startsWith("purge-user-")) {
    return "Gallring av användardata";
  }
  return `${tableLabel(tableName)} #${recordId}`;
}

// Svenska etiketter för de råa DB-kolumnnamnen i changed_fields/old_data/
// new_data. Kolumnerna kommer från AUDITED_TABLES
// (app/utils/database.py:2434-2451). Grunden är AD_FIELD_LABELS i
// stamboken-drift:docs/design/design_handoff_admin/surfaces/admin-ui.jsx:4-12.
//
// OBS de känsliga nycklarna sist: värdena stryps redan server-side
// (SENSITIVE_AUDIT_KEYS, app/utils/data_access.py:3591-3608) men
// changed_fields stryps INTE — mappningen garanterar att ett rått
// kolumnnamn aldrig renderas i DOM:en (14-audit-log-viewer.spec.ts:63-64).
export const FIELD_LABELS: Record<string, string> = {
  // hbuser
  username: "Användarnamn",
  fullname: "Fullständigt namn",
  email: "E-post",
  validated: "Webbkurs genomförd",
  v2_prod_access: "Riktiga stamboken",
  is_active: "Aktiv",
  privileges: "Roller",
  last_active: "Senast aktiv",
  uuid: "Unikt id",
  profile_picture: "Profilbild",
  google_name: "Google-namn",
  google_email: "Google-e-post",
  google_picture: "Google-bild",
  use_google_picture: "Använd Google-bild",
  // herd
  herd: "Besättningsnummer",
  herd_id: "Besättning",
  herd_name: "Besättningsnamn",
  name: "Namn",
  genebank: "Genbank",
  genebank_id: "Genbank",
  membership_id: "Medlemskap",
  start_date: "Startdatum",
  physical_address: "Adress",
  location: "Ort",
  coordinates: "Koordinater",
  email_verified: "E-post bekräftad",
  www: "Hemsida",
  mobile_phone: "Mobiltelefon",
  wire_phone: "Fast telefon",
  latitude: "Latitud",
  longitude: "Longitud",
  bank_account_number: "Kontonummer",
  bank_name: "Bank",
  // individual
  origin_herd_id: "Ursprungsbesättning",
  certificate: "Intyg",
  digital_certificate: "Digitalt intyg",
  foot_ring: "Fotring",
  number: "Individnummer",
  sex: "Kön",
  color_id: "Färg",
  color_note: "Färganteckning",
  death_date: "Dödsdatum",
  death_note: "Dödsorsak",
  notes: "Anteckningar",
  eye_color: "Ögonfärg",
  claw_color: "Klofärg",
  belly_color: "Bukfärg",
  hair_notes: "Pälsanteckningar",
  has_photo: "Har foto",
  butchered: "Slaktad",
  castration_date: "Kastreringsdatum",
  voided: "Makulerad",
  voided_at: "Makulerad den",
  // breeding + bunny
  breeding_id: "Parning",
  breeding_herd_id: "Parningsbesättning",
  breed_date: "Parningsdatum",
  breed_notes: "Parningsanteckningar",
  birth_date: "Födelsedatum",
  birth_notes: "Födelseanteckningar",
  litter_size: "Kullstorlek",
  litter_size6w: "Kullstorlek 6 v",
  litter_number: "Kullnummer",
  slot_order: "Ordning i kullen",
  label: "Benämning",
  observed_sex: "Observerat kön",
  observed_color: "Observerad färg",
  fate: "Utfall",
  individual_id: "Kanin",
  created_at: "Skapad",
  updated_at: "Uppdaterad",
  // weight / bodyfat / sjukdom / besättningshistorik / färg
  weight: "Vikt",
  weight_date: "Vägningsdatum",
  bodyfat: "Hull",
  bodyfat_date: "Hullmätningsdatum",
  disease_id: "Sjukdom",
  diagnosis_date: "Diagnosdatum",
  healthy_date: "Friskdatum",
  from_herd_id: "Från besättning",
  signature: "Signatur",
  herd_tracking_date: "Datum",
  // herd_tracking 999.5 — holder_contact_id is only ever shown as an id
  kind: "Händelsetyp",
  operation_id: "Åtgärd",
  voided_by_user_id: "Ångrad av",
  voided_reason: "Anledning till ångring",
  voided_operation_id: "Ångrad i åtgärd",
  yearly_herd_report_id: "Årsrapport",
  transfer_id: "Försäljning",
  holder_contact_id: "Köparkontakt (id)",
  comment: "Kommentar",
  // authenticators
  user_id: "Användare",
  auth: "Inloggningsmetod",
  // systemhändelser (markörrader, app/utils/data_access.py:4159-4165)
  sessions_cleared: "Avslutade sessioner",
  // känsliga kolumner — får aldrig visas med sitt råa namn
  auth_data: "Inloggningsuppgifter (dolda)",
  password_hash: "Lösenord (dolt)",
  password: "Lösenord (dolt)",
  salt: "Lösenord (dolt)",
};

/**
 * Svensk etikett för ett DB-kolumnnamn. Faller tillbaka i tur och ordning
 * på: exakt träff → "<fält>_privacy" (herd har tio sådana kolumner) →
 * "<fält>_id" (peewees FK-kolumnnamn) → råsträngen.
 */
export function fieldLabel(field: string): string {
  const exact = FIELD_LABELS[field];
  if (exact) return exact;
  if (field.endsWith("_privacy")) {
    return `${fieldLabel(field.slice(0, -"_privacy".length))} (synlighet)`;
  }
  if (field.endsWith("_id")) {
    const base = FIELD_LABELS[field.slice(0, -"_id".length)];
    if (base) return base;
  }
  return field;
}
