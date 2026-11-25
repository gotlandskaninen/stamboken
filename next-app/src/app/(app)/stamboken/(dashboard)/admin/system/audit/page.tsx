import Link from "next/link";
import { Alert, Stack, Typography } from "@mui/material";
import { LinkButton } from "../../_components/AdminLink";
import { fetchApi } from "@/lib/api";
import { AdminBackLink } from "../../_components/AdminBackLink";
import { SystemPillNav } from "../../_components/SystemPillNav";
import { requireAdmin } from "../../_lib/requireAdmin";
import { AuditLogClient, type AuditRow } from "./AuditLogClient";
import { MatrikelAuditClient } from "./MatrikelAuditClient";
import type { MatrikelAuditPage } from "@/app/(app)/medlem/matrikel/types";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";

export const dynamic = "force-dynamic";

interface AuditLogResponse {
  rows: AuditRow[];
  total: number;
  page: number;
  per_page: number;
}

// Filter param names: table, record_id, changed_by, from, to, op, page.
const FILTER_KEYS = [
  "table",
  "record_id",
  "changed_by",
  "from",
  "to",
  "op",
  "page",
] as const;

// source=matrikel: matrikelns ändringslogg (matrikel_audit, #244) i stället
// för audit_log. Egen endpoint, egna filter.
const MATRIKEL_FILTER_KEYS = [
  "action",
  "actor",
  "membership_id",
  "from",
  "to",
  "page",
] as const;

// Två källor, två länkar — samma pill-mönster som SystemPillNav.
function SourcePills({ matrikel }: { matrikel: boolean }) {
  const pill = (active: boolean) =>
    active ? `${styles["ad-pill"]} ${styles["is-active"]}` : styles["ad-pill"];
  return (
    <nav aria-label="Loggens källa" className={styles["ad-pill-row"]}>
      <Link
        href="/stamboken/admin/system/audit"
        aria-current={matrikel ? undefined : "page"}
        className={pill(!matrikel)}
      >
        Stamboken
      </Link>
      <Link
        href="/stamboken/admin/system/audit?source=matrikel"
        aria-current={matrikel ? "page" : undefined}
        className={pill(matrikel)}
      >
        Matrikeln
      </Link>
    </nav>
  );
}

async function matrikelAudit(sp: Record<string, string | undefined>) {
  const qs = new URLSearchParams();
  for (const k of MATRIKEL_FILTER_KEYS) {
    if (sp[k]) qs.set(k, sp[k] as string);
  }
  let body: MatrikelAuditPage | null = null;
  try {
    body = await fetchApi<MatrikelAuditPage>(
      `/v2/members/audit?${qs.toString()}`,
      { forceProd: true },
    );
  } catch {
    body = null;
  }
  if (body === null) {
    return (
      <Alert severity="error" sx={{ mt: 2 }}>
        <Typography gutterBottom>
          <strong>Kunde inte läsa matrikelns logg just nu.</strong> Försök igen
          om en stund.
        </Typography>
        <LinkButton
          href={`/stamboken/admin/system/audit?source=matrikel&${qs.toString()}`}
          variant="outlined"
        >
          Försök igen
        </LinkButton>
      </Alert>
    );
  }
  return (
    <>
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>
          Matrikelns logg <span className={ds["ad-count"]}>{body.total}</span>
        </h2>
      </div>
      <MatrikelAuditClient
        rows={body.rows}
        total={body.total}
        page={body.page}
        perPage={body.per_page}
        filters={{
          action: sp.action ?? "",
          actor: sp.actor ?? "",
          membership_id: sp.membership_id ?? "",
          from: sp.from ?? "",
          to: sp.to ?? "",
        }}
      />
    </>
  );
}

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  await requireAdmin(); // Page-level gate, layout renders concurrently
  const sp = await searchParams;
  if (sp.source === "matrikel") {
    return (
      <>
        <AdminBackLink href="/stamboken/admin/system" label="System" />
        <SystemPillNav current="audit" />
        <SourcePills matrikel />
        {await matrikelAudit(sp)}
      </>
    );
  }
  const qs = new URLSearchParams();
  for (const k of FILTER_KEYS) {
    if (sp[k]) qs.set(k, sp[k] as string);
  }

  let body: AuditLogResponse | null = null;
  try {
    body = await fetchApi<AuditLogResponse>(
      `/v2/admin/audit-log?${qs.toString()}`,
      { forceProd: true },
    );
  } catch {
    body = null; // 500/503 (or 5s statement_timeout) → error surface below
  }

  const retryHref = `/stamboken/admin/system/audit?${qs.toString()}`;

  return (
    <>
      <AdminBackLink href="/stamboken/admin/system" label="System" />
      <SystemPillNav current="audit" />
      <SourcePills matrikel={false} />
      {body === null ? (
        // Verbatim error surface — the layout/landing keep working.
        <Alert severity="error" sx={{ mt: 2 }}>
          <Typography gutterBottom>
            <strong>Kunde inte läsa aktivitetsloggen just nu.</strong> Försök
            igen om en stund.
          </Typography>
          <Stack direction="row" spacing={2}>
            <LinkButton href={retryHref} variant="outlined">
              Försök igen
            </LinkButton>
            <LinkButton href="/stamboken/admin">
              Tillbaka till adminpanelen
            </LinkButton>
          </Stack>
        </Alert>
      ) : (
        <>
          <div className={ds["ad-page-head"]}>
            <h2 className={ds["ad-page-title"]}>
              Aktivitetslogg{" "}
              <span className={ds["ad-count"]}>{body.total}</span>
            </h2>
          </div>
          <AuditLogClient
            rows={body.rows}
            total={body.total}
            page={body.page}
            perPage={body.per_page}
            filters={{
              table: sp.table ?? "",
              record_id: sp.record_id ?? "",
              changed_by: sp.changed_by ?? "",
              from: sp.from ?? "",
              to: sp.to ?? "",
              op: sp.op ?? "",
            }}
          />
        </>
      )}
    </>
  );
}
