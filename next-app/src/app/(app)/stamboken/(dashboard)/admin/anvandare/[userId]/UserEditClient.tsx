"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { Avatar, FormControlLabel, Switch } from "@mui/material";
import type { AdminUserDetail, PrivilegeEntry } from "../../_lib/types";
import { operationLabel, rowTitle } from "../../_lib/auditLabels";
import { ConfirmDialog } from "../../_components/ConfirmDialog";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";
import {
  RolePicker,
  type GenebankOption,
  type HerdOption,
} from "../../_components/RolePicker";
import {
  grantRole,
  resetPassword,
  revokeRole,
  setAccountActive,
  setValidated,
  setV2ProdAccess,
  updateUserProfile,
  type ActionError,
} from "../actions";

export type AuditRow = {
  changed_at: string;
  operation: string;
  changed_by: string;
  changed_fields: string[] | null;
  // Already present in the /v2/admin/audit-log payload (see
  // system/audit/AuditLogClient.tsx:17-27) — consumed here for rowTitle().
  table_name: string;
  record_id: string;
};

type HerdWithActive = HerdOption & { is_active: boolean };

function DetailCard({
  title,
  pad = true,
  children,
}: {
  title: string;
  pad?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className="sb-card">
      <div className={ds["ad-card-head"]}>
        <h3 className={`sb-h6 ${ds["ad-card-title"]}`}>{title}</h3>
      </div>
      <div className={pad ? ds["ad-card-body"] : undefined}>{children}</div>
    </section>
  );
}

// surfaces/admin-ui.jsx:15-20
const OP_BADGE: Record<string, string> = {
  INSERT: "sb-badge-mossa",
  UPDATE: "sb-badge-himmel",
  DELETE: "ad-badge-danger",
};

export function UserEditClient({
  detail,
  actorId,
  genebanks,
  herds,
  recentAudit,
  concurrentEditWarning,
}: {
  detail: AdminUserDetail;
  actorId: number;
  genebanks: GenebankOption[];
  herds: HerdWithActive[];
  recentAudit: AuditRow[];
  concurrentEditWarning: string | null;
}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [plaintext, setPlaintext] = useState<string | null>(null);
  const [fullname, setFullname] = useState(detail.fullname ?? "");
  const [email, setEmail] = useState(detail.email ?? "");
  const [activeDialogOpen, setActiveDialogOpen] = useState(false);
  const [selfRevoke, setSelfRevoke] = useState<PrivilegeEntry | null>(null);
  // Google-only accounts can lack a username (hbuser.username is nullable).
  const displayName = detail.username ?? detail.email;

  // Runs a Server Action; ApiError/pre-check failures come back as
  // { error } and render in the red banner. Successful mutations redirect
  // to the list — the thrown NEXT_REDIRECT propagates and navigates.
  const run = (action: () => Promise<ActionError | void>) => {
    setError(null);
    startTransition(async () => {
      const result = await action();
      if (result && "error" in result) setError(result.error);
    });
  };

  const gbName = (id: number) =>
    genebanks.find((g) => g.id === id)?.name ?? `genbank ${id}`;
  const herdLabel = (id: number) => {
    const h = herds.find((x) => x.id === id);
    return h
      ? `${h.herd}${h.herd_name ? ` — ${h.herd_name}` : ""}`
      : `besättning ${id}`;
  };
  const roleLabel = (p: PrivilegeEntry) => {
    // types.ts merges manager+viewer into one union member, so isolate the
    // owner and the unscoped (admin, matrikel_admin) cases first — the
    // remaining member carries `genebank`.
    if (p.level === "admin") return "Administratör";
    if (p.level === "matrikel_admin") return "Matrikeladministratör";
    if (p.level === "owner") return `Besättningsägare — ${herdLabel(p.herd)}`;
    if (p.level === "manager")
      return `Genbanksansvarig — ${gbName(p.genebank)}`;
    return p.level === "helper"
      ? `Genbankshjälpare — ${gbName(p.genebank)}`
      : `Granskare — ${gbName(p.genebank)}`;
  };

  // Handoff nivåbadge (README:45): Administratör skog, Genbanksansvarig
  // mossa, Besättningsägare himmel, Granskare neutral.
  const LEVEL_TEXT: Record<PrivilegeEntry["level"], string> = {
    admin: "Administratör",
    matrikel_admin: "Matrikeladministratör",
    manager: "Genbanksansvarig",
    helper: "Genbankshjälpare",
    viewer: "Granskare",
    owner: "Besättningsägare",
  };
  const LEVEL_BADGE: Record<PrivilegeEntry["level"], string> = {
    admin: "sb-badge-skog",
    matrikel_admin: "sb-badge-lera",
    manager: "sb-badge-mossa",
    helper: "sb-badge-mossa",
    viewer: "",
    owner: "sb-badge-himmel",
  };
  const roleTarget = (p: PrivilegeEntry) => {
    if (p.level === "admin" || p.level === "matrikel_admin") return null;
    if (p.level === "owner") return herdLabel(p.herd);
    return gbName(p.genebank);
  };

  const handleRevoke = (role: PrivilegeEntry) => {
    // Removing one's OWN admin entry gets a confirm modal.
    // The last-admin hard blocks (cases 1–2) live in the revokeRole
    // pre-check + the authoritative backend 409 → red banner here.
    if (role.level === "admin" && detail.id === actorId) {
      setSelfRevoke(role);
      return;
    }
    run(() => revokeRole(detail.id, role));
  };

  return (
    <>
      {!detail.is_active && (
        <div
          role="alert"
          className={`${ds["ad-banner"]} ${ds["ad-banner-danger"]}`}
        >
          Kontot är inaktiverat
        </div>
      )}
      {concurrentEditWarning && (
        <div
          role="status"
          className={`${ds["ad-banner"]} ${ds["ad-banner-warning"]}`}
        >
          {concurrentEditWarning}
        </div>
      )}
      {error && (
        <div
          role="alert"
          className={`${ds["ad-banner"]} ${ds["ad-banner-danger"]}`}
        >
          {error}
        </div>
      )}

      <div className={ds["ad-detail-grid"]}>
        <div className={ds["ad-col"]}>
          {/* Edit profile — username is immutable. */}
          <DetailCard title="Profil">
            <div className={ds["ad-form"]}>
              <div>
                <label className="sb-label" htmlFor="ad-username">
                  Användarnamn
                </label>
                <input
                  id="ad-username"
                  className="sb-input"
                  value={detail.username ?? ""}
                  disabled
                  readOnly
                />
              </div>
              <div>
                <label className="sb-label" htmlFor="ad-fullname">
                  Fullständigt namn
                </label>
                <input
                  id="ad-fullname"
                  className="sb-input"
                  value={fullname}
                  onChange={(e) => setFullname(e.target.value)}
                />
              </div>
              <div>
                <label className="sb-label" htmlFor="ad-email">
                  E-post
                </label>
                <input
                  id="ad-email"
                  className="sb-input"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div>
                <button
                  type="button"
                  className="sb-btn"
                  disabled={pending}
                  onClick={() =>
                    run(() => updateUserProfile(detail.id, { fullname, email }))
                  }
                >
                  Spara
                </button>
              </div>
            </div>
          </DetailCard>

          {/* Roles — expanded entries with resolved names + RolePicker. */}
          <DetailCard title="Roller">
            {detail._privileges.length === 0 ? (
              <p className={ds["ad-hint"]}>Inga roller tilldelade.</p>
            ) : (
              <ul className={styles["ad-role-list"]}>
                {detail._privileges.map((p, i) => (
                  <li key={`${p.level}-${i}`} className={styles["ad-role-row"]}>
                    <span className={`sb-badge ${LEVEL_BADGE[p.level]}`}>
                      {LEVEL_TEXT[p.level]}
                    </span>
                    {roleTarget(p) && (
                      <span className={styles["ad-role-target"]}>
                        {roleTarget(p)}
                      </span>
                    )}
                    <button
                      type="button"
                      className={`sb-btn sb-btn-ghost sb-btn-sm ${styles["ad-role-remove"]}`}
                      aria-label={`Ta bort ${roleLabel(p)}`}
                      disabled={pending}
                      onClick={() => handleRevoke(p)}
                    >
                      Ta bort
                    </button>
                  </li>
                ))}
              </ul>
            )}
            <hr className="sb-rule" />
            <div className={styles["ad-role-add"]}>
              <RolePicker
                genebanks={genebanks}
                herds={herds.filter((h) => h.is_active)}
                disabled={pending}
                onGrant={(role) => run(() => grantRole(detail.id, role))}
              />
            </div>
          </DetailCard>

          {/* Password reset — plaintext shown exactly once. */}
          <DetailCard title="Lösenord">
            {plaintext === null ? (
              <>
                <p className={ds["ad-hint"]}>
                  Det nya lösenordet visas endast en gång. Skicka det via en
                  säker kanal — inte sms eller e-post.
                </p>
                <button
                  type="button"
                  className="sb-btn sb-btn-secondary"
                  disabled={pending}
                  onClick={() => {
                    setError(null);
                    startTransition(async () => {
                      const result = await resetPassword(detail.id);
                      if ("error" in result) setError(result.error);
                      else setPlaintext(result.plaintext);
                    });
                  }}
                >
                  Återställ lösenord
                </button>
              </>
            ) : (
              <div className={`${ds["ad-banner"]} ${ds["ad-banner-warning"]}`}>
                <div>
                  <strong>Nytt lösenord för {displayName}:</strong>{" "}
                  <code>{plaintext}</code>
                </div>
                <p>
                  Detta lösenord visas endast en gång. Skicka det till
                  användaren via en säker kanal, till exempel Signal eller
                  telefonsamtal. Använd inte sms eller e-post.
                </p>
                <div className={styles["ad-role-add"]}>
                  <button
                    type="button"
                    className="sb-btn sb-btn-secondary sb-btn-sm"
                    onClick={() => navigator.clipboard.writeText(plaintext)}
                  >
                    Kopiera
                  </button>
                  <button
                    type="button"
                    className="sb-btn sb-btn-sm"
                    onClick={() => {
                      // [Klar] → back to the user detail view.
                      setPlaintext(null);
                      router.refresh();
                    }}
                  >
                    Klar
                  </button>
                </div>
              </div>
            )}
          </DetailCard>
        </div>

        <div className={ds["ad-col"]}>
          {/* The three flags. */}
          <DetailCard title="Status och åtkomst">
            <div className={styles["ad-switch-stack"]}>
              <div>
                <FormControlLabel
                  control={
                    <Switch
                      checked={detail.v2_prod_access}
                      disabled={pending}
                      onChange={(e) =>
                        run(() => setV2ProdAccess(detail.id, e.target.checked))
                      }
                    />
                  }
                  label="Tillgång till den riktiga stamboken i den nya versionen"
                />
              </div>
              <div>
                <FormControlLabel
                  control={
                    <Switch
                      checked={detail.validated}
                      disabled={pending}
                      onChange={(e) =>
                        run(() => setValidated(detail.id, e.target.checked))
                      }
                    />
                  }
                  label="Webbkurs genomförd (validerad)"
                />
                <div className={styles["ad-switch-hint"]}>
                  Endast information för administratörer — ger inte användaren
                  några behörigheter.
                </div>
              </div>
              <div>
                <FormControlLabel
                  control={
                    <Switch
                      checked={detail.is_active}
                      disabled={pending}
                      onChange={() => setActiveDialogOpen(true)}
                    />
                  }
                  label="Kontot är aktivt"
                />
                <div className={styles["ad-switch-hint"]}>
                  Inaktivering avslutar alla sessioner. Kontot kan återaktiveras
                  när som helst.
                </div>
              </div>
            </div>
          </DetailCard>

          {/* Google identity block when linked. */}
          {detail.google_email && (
            <DetailCard title="Google-konto länkat">
              <div className={styles["ad-google-row"]}>
                {detail.google_picture && (
                  <Avatar
                    src={detail.google_picture}
                    alt=""
                    sx={{ width: 36, height: 36 }}
                  />
                )}
                <div>
                  {detail.google_name ?? "(namn saknas)"}
                  <div className="sb-meta">{detail.google_email}</div>
                </div>
              </div>
            </DetailCard>
          )}

          {/* Recent activity — top 10 audit rows written BY the user
              (changed_by = username). Changes TO the account: audit viewer,
              record_id filter. */}
          <DetailCard title="Senaste aktivitet" pad={false}>
            {!detail.username || recentAudit.length === 0 ? (
              <p className={`${ds["ad-hint"]} ${ds["ad-card-body"]}`}>
                Ingen aktivitet att visa.
              </p>
            ) : (
              <div className={styles["ad-activity"]}>
                {recentAudit.map((r, i) => (
                  <div
                    key={`${r.changed_at}-${i}`}
                    className={styles["ad-activity-row"]}
                  >
                    <span
                      className={`sb-badge ${
                        OP_BADGE[r.operation] === "ad-badge-danger"
                          ? styles["ad-badge-danger"]
                          : (OP_BADGE[r.operation] ?? "")
                      }`}
                    >
                      {operationLabel(r.operation)}
                    </span>
                    <div className={styles["ad-activity-body"]}>
                      <div className={styles["ad-activity-title"]}>
                        {rowTitle(r.table_name, r.record_id)}
                      </div>
                      <div className="sb-meta">
                        {new Date(r.changed_at).toLocaleString("sv-SE", {
                          timeZone: "Europe/Stockholm",
                        })}
                        {r.changed_fields?.length
                          ? ` · ${r.changed_fields.join(", ")}`
                          : ""}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </DetailCard>
        </div>
      </div>

      {/* Activate/deactivate confirm dialog. */}
      <ConfirmDialog
        open={activeDialogOpen}
        title={detail.is_active ? "Inaktivera kontot?" : "Aktivera kontot?"}
        body={
          detail.is_active
            ? `${displayName} kan inte längre logga in och alla aktiva ` +
              "sessioner avslutas. Kontot kan återaktiveras när som helst."
            : `${displayName} kan logga in igen.`
        }
        confirmLabel={detail.is_active ? "Inaktivera" : "Aktivera"}
        confirmColor={detail.is_active ? "error" : "primary"}
        onClose={() => setActiveDialogOpen(false)}
        onConfirm={() => {
          setActiveDialogOpen(false);
          run(() => setAccountActive(detail.id, !detail.is_active));
        }}
      />

      {/* Removing own admin while other admins exist. */}
      <ConfirmDialog
        open={selfRevoke !== null}
        title="Ta bort din administratörsroll?"
        body="Du loggas ut från adminpanelen. Är du säker på att du vill fortsätta?"
        confirmLabel="Ta bort rollen"
        confirmColor="error"
        onClose={() => setSelfRevoke(null)}
        onConfirm={() => {
          const role = selfRevoke;
          setSelfRevoke(null);
          if (role) run(() => revokeRole(detail.id, role));
        }}
      />
    </>
  );
}
