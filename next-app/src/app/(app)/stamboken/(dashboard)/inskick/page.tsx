import Link from "next/link";
import { fetchApi } from "@/lib/api";
import { Masthead } from "@/components/shell/Masthead";
import { STATUS_BADGE, statusText, type Inskick } from "@/lib/inkorg";
import styles from "./inskick.module.css";

export const dynamic = "force-dynamic";

export const metadata = { title: "Mina inskick" };

export default async function MinaInskickPage() {
  // Opening this page also marks the user's "klart" notices as read.
  const { items } = await fetchApi<{ items: Inskick[] }>(
    "/v2/inkorg/mina-inskick",
  );

  return (
    <>
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
        {items.length === 0 ? (
          <section className="sb-card">
            <div className={styles.cardBody}>
              <p className={styles.note} style={{ margin: 0 }}>
                Här ser du de intyg du har skickat in och hur långt vi har
                kommit med dem. Ladda upp ett foto av ett pappersintyg så läser
                vi in kaninen åt dig.
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
                  <span className="sb-meta">
                    {new Date(it.received_at).toLocaleDateString("sv-SE")}
                  </span>
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
