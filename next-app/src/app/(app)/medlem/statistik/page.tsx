import { fetchApi } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { Masthead } from "@/components/shell/Masthead";
import ds from "@/styles/ds-admin.module.css";
import styles from "../medlem.module.css";
import { ExportButtons } from "../matrikel/ExportButtons";

export const dynamic = "force-dynamic";

// Contract with GET /api/v2/members/stats: memberships
// and persons are counted separately; friexemplar are excluded from the
// membership/person counts and reported on their own. The response is
// nested exactly as the member_stats serializer emits it.
type Stats = {
  memberships: {
    total: number;
    active: number;
    inactive: number;
    pending: number;
    new_this_year: number;
  };
  persons: {
    total: number;
    active: number;
  };
  friexemplar: number;
};

export default async function StatisticsPage() {
  const stats = await fetchApi<Stats>("/v2/members/stats");
  const user = await getUser();
  // Export is admin-gated; managers see stats but not the export buttons.
  const canExport = Boolean(user?.is_admin) || Boolean(user?.is_matrikel_admin);

  return (
    <>
      <Masthead
        eyebrow="Matrikel"
        title="Styrelsestatistik"
        meta="Medlemskap, personer och friexemplar"
        actions={canExport ? <ExportButtons /> : undefined}
      />
      <div className={styles.container}>
        <div className={`sb-card ${ds["ad-status-strip"]}`}>
          <StatCell label="Medlemskap totalt" value={stats.memberships.total} />
          <StatCell
            label="Aktiva medlemskap"
            value={stats.memberships.active}
          />
          <StatCell
            label="Inaktiva medlemskap"
            value={stats.memberships.inactive}
          />
          <StatCell
            label="Väntande medlemskap"
            value={stats.memberships.pending}
          />
        </div>
        <div className={`sb-card ${ds["ad-status-strip"]}`}>
          <StatCell label="Personer" value={stats.persons.total} />
          <StatCell label="Aktiva personer" value={stats.persons.active} />
          <StatCell label="Friexemplar" value={stats.friexemplar} />
          <StatCell label="Nya i år" value={stats.memberships.new_this_year} />
        </div>
        <p className={ds["ad-hint"]}>
          Friexemplar (tidningsutbyten m.m.) ingår inte i medlemskaps- eller
          personantalen ovan.
        </p>
      </div>
    </>
  );
}

function StatCell({ label, value }: { label: string; value: number }) {
  return (
    <div className={ds["ad-status-cell"]}>
      <div className={ds["ad-status-val"]}>{value}</div>
      <div className="sb-stat-label">{label}</div>
    </div>
  );
}
