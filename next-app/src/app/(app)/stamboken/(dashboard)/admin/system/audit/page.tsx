import { Alert, Stack, Typography } from "@mui/material";
import { LinkButton } from "../../_components/AdminLink";
import { fetchApi } from "@/lib/api";
import { AdminBackLink } from "../../_components/AdminBackLink";
import { SystemPillNav } from "../../_components/SystemPillNav";
import { requireAdmin } from "../../_lib/requireAdmin";
import { AuditLogClient, type AuditRow } from "./AuditLogClient";
import ds from "@/styles/ds-admin.module.css";

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

export default async function AuditPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  await requireAdmin(); // Page-level gate, layout renders concurrently
  const sp = await searchParams;
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
