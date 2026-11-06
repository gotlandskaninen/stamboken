/**
 * Swedish UI copy used as selectors.
 *
 * SPEC-PINNED constants quote the design spec verbatim (section cited) —
 * if a spec assertion fails on one of these, the IMPLEMENTATION drifted
 * from the spec; fix the implementation.
 *
 * TASK-ANCHORED constants are component copy owned by Fas C tasks
 * (Task 24–29). If a Fas C task shipped different Swedish copy, update the
 * constant here (one place) — never rewrite the test flows.
 */

// ---- Spec-pinned ----
export const MODE_PROMPT_BUTTON = "Byt till riktiga stamboken"; // §1.1 + §11.5 (stable across both copy drafts)
export const MODE_PROMPT_HEADING =
  /Adminpanelen (finns i den riktiga stamboken|ligger i riktiga stamboken|kör mot skarpa databasen)/; // §1.1/§11.5; klarspråksrevision 2026-08-04 (Codex-språkgranskning)
export const SELF_LOCKOUT_BANNER =
  "Den sista administratörsrollen kan inte tas bort."; // §5.3 case 1 red banner (klarspråksrevision 2026-08-04)
export const DEACTIVATED_BANNER = "Kontot är inaktiverat"; // §4.12 detail-page red banner
export const MASS_LOGOUT_PHRASE = "LOGGA UT ALLA"; // §3.3.2 type-to-confirm
export const MASS_LOGOUT_WARNING =
  "Alla inloggade användare loggas ut — inklusive du själv."; // §3.3.2 verbatim
export const SYNC_STALE_BANNER =
  "Demoversionen har inte uppdaterats det senaste dygnet."; // §3.3.3 (klarspråksrevision 2026-08-04)
export const PASSWORD_RESET_ONCE = "Detta lösenord visas endast en gång"; // §5.7
export const PASSWORD_RESET_HEADING = /Nytt lösenord för/; // §5.7
export const NAV_SESSIONS = "Aktiva användare"; // §2.2 SYSTEM group (klarspråksrevision 2026-08-04)
export const NAV_AUDIT = "Aktivitetslogg"; // §2.2
export const NAV_SYNC = "Demosynkronisering"; // §2.2 (klarspråksrevision 2026-08-04)
export const NAV_RATELIMIT = "Anropsgränser"; // §2.2 (klarspråksrevision 2026-08-04)
export const NAV_ALL_USERS = "Alla användare"; // §2.2
export const MANAGER_HERDS_NAV = /Besättningar i Gotlandskanin/; // §2.2 manager variant

// ---- Task-anchored (Fas C component copy) ----
export const PANEL_HEADING = "Adminpanel"; // Task 24/25 landing heading → C8 layout masthead <h1>; getByRole("heading") is level-agnostic
export const SEARCH_FIELD = /Sök/; // Task 26/27 list search fields
export const FULLNAME_FIELD = "Fullständigt namn"; // Task 26 profile form
export const SAVE_BUTTON = "Spara"; // Task 26/27/28 forms
export const CREATE_HERD_BUTTON = "Skapa besättning"; // Task 27 create form
export const ROLE_LEVEL_FIELD = "Roll"; // Task 26 RolePicker level select (label "Roll")
export const ROLE_HERD_FIELD = "Besättning"; // Task 26 RolePicker herd autocomplete
export const ROLE_ADD_BUTTON = "Lägg till roll"; // Task 26 RolePicker submit
export const ROLE_REMOVE_BUTTON = /^Ta bort/; // Task 26 / C12 privilege-row revoke — ghost button, aria-label "Ta bort <roll>"
export const ROLE_REMOVE_ADMIN = "Ta bort Administratör"; // C12: exact accessible name of the admin row's revoke button
export const V2_TOGGLE = /v2_prod_access|[Rr]iktiga stamboken/; // Task 26 flag switch label
export const VALIDATED_TOGGLE = /[Vv]aliderad|validated/; // Task 26 flag switch label
export const ACTIVE_TOGGLE = /Kontot är aktivt/; // Task 26 is_active toggle (klarspråksrevision 2026-08-04)
export const INACTIVE_FILTER = "Inaktiv"; // Task 26 list filter (§3.1 "konto Aktiv/Inaktiv")
export const CONFIRM_BUTTON = /Inaktivera|Aktivera|Logga ut alla/; // Task 26/29 ConfirmDialog confirm — per-action verb labels (confirmLabel)
export const RESET_PASSWORD_BUTTON = /Återställ lösenord/; // Task 26 (§3.1 manual password reset)
export const DONE_BUTTON = "Klar"; // §5.7 [Kopiera] [Klar]
export const GENEBANK_FIELD = "Genbank"; // Task 27 create-herd picker
export const HERD_NUMBER_FIELD = /Besättningsnummer|Besättnings-?ID/; // Task 27 create-herd manual number (klarspråksrevision 2026-08-04)
export const HERD_NAME_FIELD = "Besättningsnamn"; // Task 27 create-herd name field — matched with { exact: true } in spec 12 to avoid the contact "Namn" textbox on the same form (CreateHerdForm.tsx has both)
export const DUPLICATE_HERD_ERROR = /finns redan/i; // Task 27 Swedish duplicate-ID field error (§3.2)
export const MASS_LOGOUT_BUTTON = /Logga ut alla/i; // Task 29 red button (§3.3.2)

// ---- C8 admin chrome (Fas C slice 3 — old sidebar/breadcrumbs removed) ----
export const TAB_NAV_LABEL = "Adminpanelens avsnitt"; // C8 AdminTabs <nav aria-label>
export const TAB_OVERVIEW = "Översikt"; // C8 tab row — Översikt tab (href /stamboken/admin)
export const TAB_USERS = "Användare"; // C8 tab row — replaces the old sidebar's "Alla användare" (NAV_ALL_USERS)
export const BACK_TO_USERS = /^← Alla användare$/; // C8 AdminBackLink, user detail
export const BACK_TO_HERDS = /^← Alla besättningar$/; // C8 AdminBackLink, herd detail + ny
export const BACK_TO_GENEBANKS = /^← Alla genbanker$/; // C8 AdminBackLink, genebank detail
export const BACK_TO_SYSTEM = /^← System$/; // C8 AdminBackLink, system sub-pages
