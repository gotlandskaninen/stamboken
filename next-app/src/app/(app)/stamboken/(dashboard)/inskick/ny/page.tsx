import { ApiError, fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { Masthead } from "@/components/shell/Masthead";
import type { MyMembership } from "../../profil/types";
import { UploadForm } from "./UploadForm";
import styles from "../inskick.module.css";

export const dynamic = "force-dynamic";

export const metadata = { title: "Ladda upp intyg" };

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

  return (
    <>
      <Masthead eyebrow="Mina inskick" title="Ladda upp intyg" />
      <div className={styles.container}>
        {herds.length === 0 ? (
          <section className="sb-card">
            <div className={styles.cardBody}>
              <p className={styles.note} style={{ margin: 0 }}>
                Du har ingen besättning att ladda upp för. Kontakta
                matrikelansvarig om det borde finnas en.
              </p>
            </div>
          </section>
        ) : (
          <UploadForm herds={herds} />
        )}
      </div>
    </>
  );
}
