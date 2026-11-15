import { ApiError, fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { getInboxCount } from "@/lib/inkorg-server";
import type { GenebankHerd } from "@/utils/saleRules";
import { Masthead } from "@/components/shell/Masthead";
import type { MyMembership } from "../../profil/types";
import { UploadForm } from "./UploadForm";
import styles from "../inskick.module.css";

export const dynamic = "force-dynamic";

export const metadata = { title: "Ladda upp intyg" };

/** Every herd the user can see, for someone who works in the queue (the API lets them upload for any herd). */
async function searchableHerds(): Promise<GenebankHerd[]> {
  const { genebanks } = await fetchApi<{ genebanks: { id: number }[] }>(
    "/genebanks",
  ).catch(() => ({ genebanks: [] }));
  const lists = await Promise.all(
    genebanks.map((g) =>
      fetchApi<{ herds: GenebankHerd[] }>(`/v2/genebank/${g.id}/herds`)
        .then((r) => r.herds)
        .catch(() => []),
    ),
  );
  return lists.flat();
}

export default async function NyttInskickPage() {
  const user = await requireUser();
  // Owners come from the session; skötare only appear in the membership.
  const membership = await fetchApi<MyMembership>("/v2/my-membership").catch(
    (e) => {
      if (e instanceof ApiError && e.status === 404) return null;
      throw e;
    },
  );
  const herds = [
    ...new Set([
      ...(user.is_owner ?? []),
      ...(membership?.membership.herds.map((h) => h.herd) ?? []),
    ]),
  ].sort();

  const worksInQueue = await getInboxCount()
    .then((c) => c.works_in_queue)
    .catch(() => false);
  const herdOptions = worksInQueue ? await searchableHerds() : undefined;

  return (
    <>
      <Masthead eyebrow="Mina inskick" title="Ladda upp intyg" />
      <div className={styles.container}>
        {herds.length === 0 && !herdOptions ? (
          <section className="sb-card">
            <div className={styles.cardBody}>
              <p className={styles.note} style={{ margin: 0 }}>
                Du har ingen besättning att ladda upp för. Kontakta
                matrikelansvarig om det borde finnas en.
              </p>
            </div>
          </section>
        ) : (
          <UploadForm herds={herds} herdOptions={herdOptions} />
        )}
      </div>
    </>
  );
}
