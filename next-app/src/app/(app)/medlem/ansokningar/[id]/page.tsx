import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, fetchApi } from "@/lib/api";
import { Masthead } from "@/components/shell/Masthead";
import ds from "@/styles/ds-admin.module.css";
import styles from "../../medlem.module.css";
import { ApplicationDetailClient } from "./ApplicationDetailClient";

export const dynamic = "force-dynamic";

type Application = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  phone: string | null;
  address: string | null;
  postal_code: string | null;
  city: string | null;
  motivation: string | null;
  status: string;
  created_at: string;
};

export default async function ApplicationDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  let app: Application;
  try {
    app = await fetchApi<Application>(`/v2/member-applications/${id}`);
  } catch (err) {
    // Only 404 should trigger notFound. 403, 500, network errors etc.
    // should bubble up to Next.js error boundaries so the user sees a
    // real error — not a misleading "not found" page.
    if (err instanceof ApiError && err.status === 404) notFound();
    throw err;
  }

  const submitted = new Date(app.created_at).toLocaleString("sv-SE");

  return (
    <>
      <Masthead
        eyebrow="Matrikel"
        title={`Ansökan från ${app.first_name} ${app.last_name}`}
        meta={`Inskickad ${submitted}`}
      />
      <div className={styles.container}>
        <Link href="/medlem/ansokningar" className={ds["ad-back"]}>
          ← Medlemsansökningar
        </Link>
        <div className={ds["ad-detail-grid"]}>
          <section className="sb-card">
            <div className={ds["ad-card-head"]}>
              <h3 className={`sb-h6 ${ds["ad-card-title"]}`}>Uppgifter</h3>
            </div>
            <div className={ds["ad-card-body"]}>
              <dl className={ds["ad-kv"]}>
                <Row
                  label="Namn"
                  value={`${app.first_name} ${app.last_name}`}
                />
                <Row label="E-post" value={app.email} />
                <Row label="Telefon" value={app.phone || "–"} />
                {/* Structured address (Phase 19 T2a): gatuadress, postnummer
                    och postort är egna fält. */}
                <Row label="Gatuadress" value={app.address || "–"} />
                <Row label="Postnummer" value={app.postal_code || "–"} />
                <Row label="Postort" value={app.city || "–"} />
                <Row
                  label="Motivering"
                  value={app.motivation || "(ingen angiven)"}
                />
                <Row label="Inskickad" value={submitted} />
              </dl>
            </div>
          </section>
          <section className="sb-card">
            <div className={ds["ad-card-head"]}>
              <h3 className={`sb-h6 ${ds["ad-card-title"]}`}>Granskning</h3>
            </div>
            <div className={ds["ad-card-body"]}>
              <ApplicationDetailClient
                applicationId={app.id}
                status={app.status}
              />
            </div>
          </section>
        </div>
      </div>
    </>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}
