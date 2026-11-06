import { fetchApi } from "@/lib/api";
import { AdminBackLink } from "../../_components/AdminBackLink";
import { SystemPillNav } from "../../_components/SystemPillNav";
import { requireAdmin } from "../../_lib/requireAdmin";
import type { SyncStatus } from "../../_lib/types";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../admin.module.css";

export const dynamic = "force-dynamic";

export default async function SynkPage() {
  await requireAdmin(); // Page-level gate, layout renders concurrently
  const status = await fetchApi<SyncStatus>("/v2/admin/sync-status", {
    forceProd: true,
  });
  // An empty demo_sync_status table yields stale=true with a null
  // row — render the empty state defensively. started_at drives the narrowing
  // (string | null) so the detail block only reads a non-null timestamp.
  const startedAt = status.started_at;
  return (
    <>
      <AdminBackLink href="/stamboken/admin/system" label="System" />
      <SystemPillNav current="synk" />
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>Demosynkronisering</h2>
      </div>
      {status.stale && startedAt && (
        <div className={`${ds["ad-banner"]} ${ds["ad-banner-warning"]}`}>
          Demoversionen har inte uppdaterats det senaste dygnet.
        </div>
      )}
      {!startedAt ? (
        <p className={ds["ad-hint"]}>
          Demoversionen har ännu inte uppdaterats.
        </p>
      ) : (
        <section className="sb-card">
          <div className={ds["ad-card-head"]}>
            <h3 className={`sb-h6 ${ds["ad-card-title"]}`}>
              Senaste synkronisering
            </h3>
          </div>
          <div className={ds["ad-card-body"]}>
            <dl className={ds["ad-kv"]}>
              <div>
                <dt>Startad</dt>
                <dd className={ds["ad-cell-mono"]}>
                  {new Date(startedAt).toLocaleString("sv-SE", {
                    timeZone: "Europe/Stockholm",
                  })}
                </dd>
              </div>
              <div>
                <dt>Avslutad</dt>
                <dd className={ds["ad-cell-mono"]}>
                  {status.finished_at
                    ? new Date(status.finished_at).toLocaleString("sv-SE", {
                        timeZone: "Europe/Stockholm",
                      })
                    : "Ingen sluttid registrerad"}
                </dd>
              </div>
              <div>
                <dt>Resultat</dt>
                <dd>
                  {status.success === true && (
                    <span className="sb-badge sb-badge-mossa">Lyckades</span>
                  )}
                  {status.success === false && (
                    <span className={`sb-badge ${styles["ad-badge-danger"]}`}>
                      Misslyckades
                    </span>
                  )}
                  {status.success === null && (
                    <span className="sb-badge">Okänt</span>
                  )}
                </dd>
              </div>
              <div>
                <dt>Synkroniserade användare</dt>
                {/* RÅTT heltal — 17-synk-status.spec.ts:31 gör
                    getByText("1234"). Ingen toLocaleString, ingen
                    tusentalsavgränsare. */}
                <dd className={ds["ad-cell-mono"]}>
                  {status.rows_synced ?? "—"}
                </dd>
              </div>
            </dl>
            {status.success === false && (
              <div
                className={`${ds["ad-banner"]} ${ds["ad-banner-danger"]} ${ds["ad-banner-inset"]}`}
              >
                <p>
                  Den senaste uppdateringen misslyckades. Teknisk felinformation
                  visas nedan.
                </p>
                {status.detail && (
                  <pre className={styles["ad-pre"]}>{status.detail}</pre>
                )}
              </div>
            )}
          </div>
        </section>
      )}
      <p className={ds["ad-hint"]}>
        Här kan du bara se status. Synkroniseringen startar automatiskt varje
        natt.
      </p>
    </>
  );
}
