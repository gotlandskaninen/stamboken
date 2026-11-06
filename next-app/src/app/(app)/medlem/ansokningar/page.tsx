import { fetchApi } from "@/lib/api";
import { Masthead } from "@/components/shell/Masthead";
import ds from "@/styles/ds-admin.module.css";
import styles from "../medlem.module.css";
import { ApplicationsGridClient } from "./ApplicationsGridClient";
import type { ApplicationRow } from "./ApplicationsGridClient";

export const dynamic = "force-dynamic";

export default async function ApplicationsPage() {
  const data = await fetchApi<{ items: ApplicationRow[] }>(
    "/v2/member-applications?status=pending",
  );
  const items = data.items ?? [];

  return (
    <>
      <Masthead
        eyebrow="Matrikel"
        title="Medlemsansökningar"
        meta={`${items.length.toLocaleString("sv-SE")} väntande`}
      />
      <div className={styles.container}>
        <section className={`sb-card ${ds["ad-grid"]}`}>
          <ApplicationsGridClient rows={items} />
        </section>
      </div>
    </>
  );
}
