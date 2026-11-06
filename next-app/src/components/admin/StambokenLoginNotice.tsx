import Link from "next/link";

/**
 * Rendered above the Payload admin login form (via admin.components.beforeLogin).
 *
 * With `disableLocalStrategy`, Payload's built-in login form is empty — identity
 * comes from the Stamboken (Flask) session. Two cases land here and must not see
 * a bare empty box:
 *  (a) no / expired session — the user must sign in via Stamboken first;
 *  (b) a valid Stamboken user whose email is NOT on the editor allowlist — the
 *      flask-session strategy returns no user, so Payload shows this screen.
 * The copy below covers both: sign in via Stamboken, and if that still fails the
 * account lacks CMS permission.
 */
export default function StambokenLoginNotice() {
  return (
    <div style={{ textAlign: "center", marginBottom: 24 }}>
      <h2
        style={{
          fontFamily: "'Source Serif 4', Georgia, serif",
          fontWeight: 500,
          marginBottom: 8,
        }}
      >
        Stamboken CMS
      </h2>
      <p style={{ marginTop: 0 }}>
        Du loggar in i CMS:et med ditt Stamboken-konto.
      </p>
      <p style={{ color: "var(--theme-elevation-500, #6b6256)", fontSize: 14 }}>
        Om du redan är inloggad i Stamboken men inte kommer in här saknar ditt
        konto behörighet att redigera webbplatsen — kontakta en administratör.
      </p>
      <Link
        href="/auth/sign-in?return_to=/admin"
        style={{
          display: "inline-block",
          marginTop: 16,
          padding: "10px 20px",
          background: "#1f1b16",
          color: "#fff",
          borderRadius: 6,
          textDecoration: "none",
        }}
      >
        Logga in via Stamboken
      </Link>
    </div>
  );
}
