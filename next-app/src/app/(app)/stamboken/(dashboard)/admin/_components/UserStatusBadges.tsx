import ds from "@/styles/ds-admin.module.css";
import styles from "../admin.module.css";

/**
 * Handoff `UserStatusBadges` (surfaces/admin-ui.jsx:47-54). No `"use client"`:
 * pure markup, rendered from the RSC detail page and from the client
 * DataGrid cell.
 */
export function UserStatusBadges({
  validated,
  v2ProdAccess,
  googleLinked,
  isActive,
}: {
  validated: boolean;
  v2ProdAccess: boolean;
  googleLinked: boolean;
  isActive: boolean;
}) {
  return (
    <span className={ds["ad-badge-row"]}>
      {validated && <span className="sb-badge sb-badge-mossa">Webbkurs</span>}
      {v2ProdAccess && (
        <span className="sb-badge sb-badge-skog">Riktiga stamboken</span>
      )}
      {googleLinked && <span className="sb-badge">Google</span>}
      {!isActive && (
        <span className={`sb-badge ${styles["ad-badge-danger"]}`}>Inaktiv</span>
      )}
    </span>
  );
}
