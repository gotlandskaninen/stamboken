import Link from "next/link";
import { cookies } from "next/headers";
import { MODE_COOKIE, parseMode } from "@/lib/mode";
import { fetchApi } from "@/lib/api";
import { Masthead } from "@/components/shell/Masthead";
import {
  formatDate,
  STATUS_BADGE,
  statusText,
  type Inskick,
} from "@/lib/inkorg";
import { MarkSeen } from "./MarkSeen";
import styles from "./inskick.module.css";

export const dynamic = "force-dynamic";

export const metadata = { title: "Mina inskick" };

export default async function MinaInskickPage() {
  const demo = parseMode((await cookies()).get(MODE_COOKIE)?.value) === "demo";
  const canRead = !demo || !!process.env.API_TEST_INTERNAL_URL;
  const { items } = canRead
    ? await fetchApi<{ items: Inskick[] }>("/v2/inkorg/mina-inskick", {
        isolateDemo: true,
      })
    : { items: [] };

  return (
    <>
      {canRead && <MarkSeen />}
      <Masthead
        eyebrow="Inläsning"
        title="Mina inskick"
        actions={
          <Link href="/stamboken/inskick/ny" className="sb-btn">
            Ladda upp intyg
          </Link>
        }
      />
      <div className={styles.container}>
        {demo && (
          <p>
            Du är i testmiljön. Det du har skickat in till riktiga Stamboken
            visas inte här.
          </p>
        )}
        {items.length === 0 ? (
          <section className="sb-card">
            <div className={styles.cardBody}>
              <p className={styles.note} style={{ margin: 0 }}>
                Här ser du de intyg du har skickat in och hur långt vi har
                kommit med dem. Du kan ladda upp ett foto eller en PDF av ett
                pappersintyg.
              </p>
            </div>
          </section>
        ) : (
          items.map((it) => (
            <section
              key={it.id}
              id={`arende-${it.id}`}
              className={`sb-card ${styles.target}`}
            >
              <div className={styles.cardBody}>
                <div className={styles.row}>
                  <span className={styles.rowTitle}>
                    <strong>ärende {it.id}</strong>
                    <span
                      className={`sb-badge ${STATUS_BADGE[it.status] ?? ""}`}
                    >
                      {statusText(it.status)}
                    </span>
                  </span>
                  <span className="sb-meta">{formatDate(it.received_at)}</span>
                </div>
                <p className="sb-meta" style={{ margin: "6px 0 0" }}>
                  Besättning {it.herd}, {it.documents}{" "}
                  {it.documents === 1 ? "bild" : "bilder"}
                </p>
                {it.status === "klart" && it.individuals.length > 0 && (
                  <p className={styles.individuals}>
                    Inlagd:{" "}
                    {it.individuals.map((n, i) => (
                      <span key={n}>
                        {i > 0 && ", "}
                        <Link
                          href={`/stamboken/individ/${encodeURIComponent(n)}`}
                          className="sb-link"
                        >
                          {n}
                        </Link>
                      </span>
                    ))}
                  </p>
                )}
              </div>
            </section>
          ))
        )}
      </div>
    </>
  );
}
