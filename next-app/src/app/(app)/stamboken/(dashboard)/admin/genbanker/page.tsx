import Link from "next/link";
import { fetchApi } from "@/lib/api";
import { requireHerdAdmin } from "../_lib/requireAdmin";
import ds from "@/styles/ds-admin.module.css";
import styles from "../admin.module.css";

export const dynamic = "force-dynamic";

interface GenebankListRow {
  id: number;
  name: string;
  herds: { is_active: boolean | null }[];
}

export default async function GenebankListPage() {
  const user = await requireHerdAdmin();
  const body = await fetchApi<{ genebanks: GenebankListRow[] }>("/genebanks", {
    forceProd: true,
  });
  // /api/genebanks scopes by ACCESS (viewer included); the panel scopes by
  // MANAGEMENT — filter to managed gb's for non-admins.
  const scoped = user.is_admin
    ? body.genebanks
    : body.genebanks.filter((gb) => (user.is_manager ?? []).includes(gb.id));
  return (
    <>
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>
          Genbanker <span className={ds["ad-count"]}>{scoped.length}</span>
        </h2>
      </div>
      {scoped.length === 0 ? (
        <div className={`sb-card ${ds["ad-empty-note"]}`}>
          Inga genbanker att visa.
        </div>
      ) : (
        <div className={styles["ad-gb-grid"]}>
          {scoped.map((gb) => {
            const activeHerds = gb.herds.filter((h) => h.is_active).length;
            return (
              <section key={gb.id} className="sb-card">
                <div className={ds["ad-card-head"]}>
                  <h3 className={styles["ad-gb-title"]}>{gb.name}</h3>
                  <Link
                    href={`/stamboken/admin/genbanker/${gb.id}`}
                    className="sb-btn sb-btn-ghost sb-btn-sm"
                  >
                    Redigera
                  </Link>
                </div>
                <div className={styles["ad-gb-body"]}>
                  <dl className={ds["ad-kv"]}>
                    <div>
                      <dt>Besättningar</dt>
                      <dd>
                        {activeHerds === 1
                          ? "1 aktiv besättning"
                          : `${activeHerds} aktiva besättningar`}
                      </dd>
                    </div>
                  </dl>
                </div>
              </section>
            );
          })}
        </div>
      )}
    </>
  );
}
