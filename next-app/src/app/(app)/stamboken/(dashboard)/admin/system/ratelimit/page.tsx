import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from "@mui/material";
import { fetchApi } from "@/lib/api";
import { AdminBackLink } from "../../_components/AdminBackLink";
import { SystemPillNav } from "../../_components/SystemPillNav";
import { requireAdmin } from "../../_lib/requireAdmin";
import type { RateLimitStatus } from "../../_lib/types";
import { functionLabel, limitSv } from "../../_lib/limitSv";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";

export const dynamic = "force-dynamic";

export default async function RateLimitPage() {
  await requireAdmin(); // Page-level gate, layout renders concurrently
  const status = await fetchApi<RateLimitStatus>(
    "/v2/admin/rate-limit-status",
    { forceProd: true },
  );
  return (
    <>
      <AdminBackLink href="/stamboken/admin/system" label="System" />
      <SystemPillNav current="ratelimit" />
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>Anropsgränser</h2>
      </div>
      <div className={`sb-card ${ds["ad-status-strip"]}`}>
        <div className={ds["ad-status-cell"]}>
          <div className={ds["ad-status-val"]}>
            {status.enabled && (
              <span className={styles["ad-online-dot"]} aria-hidden="true" />
            )}
            {status.enabled ? "På" : "Av"}
          </div>
          <div className="sb-stat-label">Skydd mot för många anrop</div>
          {!status.enabled && (
            <div className="sb-meta">Avstängt i konfigurationen</div>
          )}
        </div>
        <div className={ds["ad-status-cell"]}>
          <div className={ds["ad-status-val"]}>
            {status.storage === "redis" ? "Redis" : "Minne"}
          </div>
          <div className="sb-stat-label">Lagringsmetod</div>
        </div>
        <div className={ds["ad-status-cell"]}>
          <div
            className={
              status.storage_healthy
                ? ds["ad-status-val"]
                : `${ds["ad-status-val"]} ${ds["is-danger"]}`
            }
          >
            {status.storage_healthy ? "Ja" : "Nej"}
          </div>
          <div className="sb-stat-label">Lagringen fungerar</div>
        </div>
        <div className={ds["ad-status-cell"]}>
          <div className={ds["ad-status-val"]}>
            {status.active_counter_keys ?? "—"}
          </div>
          <div className="sb-stat-label">Aktiva räknare</div>
        </div>
      </div>
      <div className={`sb-card ${ds["ad-grid"]}`}>
        <TableContainer>
          {/* MUI Table stannar (temat styr den) — 18-ratelimit-status.spec.ts:27
              gör getByRole("row").nth(1) och behöver äkta tabellsemantik.
              min-width 720px = Adminpanel.html:52. */}
          <Table size="small" sx={{ minWidth: 720 }}>
            <TableHead>
              <TableRow>
                <TableCell>Funktion</TableCell>
                <TableCell sx={{ width: 280 }}>Gräns</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {status.registered_limits.map((l) => (
                <TableRow key={`${l.endpoint}-${l.limit}`}>
                  <TableCell>
                    {functionLabel(l.endpoint)}
                    <div className={`sb-meta ${styles["ad-cell-sub"]}`}>
                      {l.endpoint}
                    </div>
                  </TableCell>
                  <TableCell>{limitSv(l.limit)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </div>
    </>
  );
}
