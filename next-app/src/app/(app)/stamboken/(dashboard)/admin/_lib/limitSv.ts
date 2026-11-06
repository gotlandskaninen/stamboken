// Frontend-only översättning av Flask-Limiters registersträngar (ingen
// API-ändring).
// Porterat från stamboken-drift:docs/design/design_handoff_admin/surfaces/admin-ui.jsx:26-33
// men med räknaren VALFRI: app-defaults stringifieras som "1000 per 1 hour"
// (app/blueprints/admin.py:492 -> str(RateLimitItem)) medan dekorerade
// routes behåller författarens literal "10 per hour"
// (app/blueprints/admin.py:408, app/herdbook.py:275/1078/1142/1544).
const LIMIT_RE = /^(\d+)\s+per\s+(?:(\d+)\s+)?(second|minute|hour|day)s?$/;

const UNITS: Record<string, [string, string]> = {
  second: ["sekund", "sekunder"],
  minute: ["minut", "minuter"],
  hour: ["timme", "timmar"],
  day: ["dygn", "dygn"],
};

/** "100 per 1 minute" → "100 anrop per minut". Okänd form → råsträngen. */
export function limitSv(limit: string): string {
  const m = LIMIT_RE.exec(limit.trim());
  if (!m) return limit;
  const [, count, multiple, unit] = m;
  const [singular, plural] = UNITS[unit];
  const window =
    !multiple || multiple === "1" ? singular : `${multiple} ${plural}`;
  return `${count} anrop per ${window}`;
}

// Flask-endpointid:n som Flask-Limiter registrerar. Nyckeln kan vara både
// "admin_reset_password" och "blueprints.admin.admin_reset_password" —
// app/tests/test_admin_blueprint.py:746 matchar med `in`, alltså slår vi
// upp både hela id:t och sista punktsegmentet.
const FUNCTION_LABELS: Record<string, string> = {
  default: "Standardgräns (alla anrop)",
  login_handler: "Inloggning",
  google_token_login: "Google-inloggning",
  edit_individual: "Redigera kanin",
  create_application: "Medlemsansökan",
  admin_grant_role: "Ändra roller (admin)",
  admin_reset_password: "Återställ lösenord (admin)",
};

/** Svenskt funktionsnamn för ett endpointid. Okänt id → råsträngen. */
export function functionLabel(endpoint: string): string {
  const exact = FUNCTION_LABELS[endpoint];
  if (exact) return exact;
  const tail = endpoint.split(".").pop() ?? endpoint;
  return FUNCTION_LABELS[tail] ?? endpoint;
}
