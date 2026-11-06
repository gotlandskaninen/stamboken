import { notFound } from "next/navigation";
import { fetchApi } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { AdminBackLink } from "../../_components/AdminBackLink";
import { UserStatusBadges } from "../../_components/UserStatusBadges";
import { requireAdmin } from "../../_lib/requireAdmin";
import type { AdminUserDetail } from "../../_lib/types";
import { UserEditClient, type AuditRow } from "./UserEditClient";
import ds from "@/styles/ds-admin.module.css";

export const dynamic = "force-dynamic";

// Envelope from GET /api/v2/admin/audit-log — verified at impl:
// data_access.query_audit_log returns { rows, total, page, per_page }.
type AuditResponse = { rows: AuditRow[]; total: number };

type GenebankShort = {
  id: number;
  name: string;
  herds: {
    id: number;
    herd: string;
    herd_name: string | null;
    is_active: boolean;
  }[];
};

const FIVE_MINUTES_MS = 5 * 60 * 1000;

export default async function AdminUserDetailPage({
  params,
}: {
  params: Promise<{ userId: string }>;
}) {
  await requireAdmin(); // Page-level gate, layout renders concurrently
  const { userId } = await params;
  const uid = Number(userId);
  if (!Number.isInteger(uid) || uid <= 0) notFound();

  const [actor, detail, recordAudit, genebanks] = await Promise.all([
    getUser(),
    fetchApi<AdminUserDetail>(`/v2/admin/users/${uid}`, {
      forceProd: true,
    }).catch(() => null),
    // Warning input: newest write TO this hbuser row.
    fetchApi<AuditResponse>(
      `/v2/admin/audit-log?table=hbuser&record_id=${uid}&per_page=1`,
      { forceProd: true },
    ).catch(() => ({ rows: [], total: 0 })),
    // GET /api/genebanks returns { genebanks: [...] } (herdbook.py:1486),
    // not a bare array — unwrap it. Admins see all genebanks + all herds.
    fetchApi<{ genebanks: GenebankShort[] }>("/genebanks", { forceProd: true })
      .then((r) => r.genebanks ?? [])
      .catch(() => [] as GenebankShort[]),
  ]);
  if (!actor) notFound();
  if (!detail) notFound(); // Missing entity → 404

  // Recent activity: top-10 audit rows written BY the user (the
  // changed_by param matches hbuser.username). Runs after the parallel
  // batch — it needs detail.username; NULL username (Google-only account)
  // skips the query and the panel shows "Ingen aktivitet att visa".
  // Changes TO the account: audit viewer, record_id filter.
  const activity = detail.username
    ? await fetchApi<AuditResponse>(
        `/v2/admin/audit-log?changed_by=${encodeURIComponent(detail.username)}&per_page=10`,
        { forceProd: true },
      ).catch(() => ({ rows: [], total: 0 }))
    : { rows: [], total: 0 };

  // Google-only accounts can lack a username (hbuser.username is nullable).
  const displayName = detail.username ?? detail.email;

  // Soft warning: newest hbuser write < 5 min old AND by someone else.
  // Async Server Component: runs once per request on the server and is never
  // re-rendered on the client, so reading wall-clock time here is safe. The
  // react-hooks/purity rule is a client-render heuristic (false-positive here).
  // eslint-disable-next-line react-hooks/purity
  const now = Date.now();
  const newest = recordAudit.rows[0];
  const concurrentEditWarning =
    newest &&
    actor.username &&
    newest.changed_by !== actor.username &&
    now - new Date(newest.changed_at).getTime() < FIVE_MINUTES_MS
      ? `Observera: ${newest.changed_by} ändrade användaren nyligen. ` +
        "Om sidan inte visar den senaste versionen kan dina ändringar " +
        "skriva över tidigare ändringar."
      : null;

  const allHerds = genebanks.flatMap((g) => g.herds);

  return (
    <>
      <AdminBackLink href="/stamboken/admin/anvandare" label="Alla användare" />
      <div className={ds["ad-page-head"]}>
        <div>
          <h2 className={ds["ad-page-title"]}>{displayName}</h2>
          <div className={ds["ad-page-sub"]}>
            {detail.fullname ?? "—"} ·{" "}
            <span className="sb-meta">{detail.email}</span>
          </div>
        </div>
        <UserStatusBadges
          validated={detail.validated}
          v2ProdAccess={detail.v2_prod_access}
          googleLinked={detail.google_linked}
          isActive={detail.is_active}
        />
      </div>

      <UserEditClient
        detail={detail}
        actorId={actor.id}
        genebanks={genebanks.map(({ id, name }) => ({ id, name }))}
        herds={allHerds}
        recentAudit={activity.rows}
        concurrentEditWarning={concurrentEditWarning}
      />
    </>
  );
}
