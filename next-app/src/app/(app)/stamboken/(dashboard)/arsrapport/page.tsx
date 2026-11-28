import Link from "next/link";
import { redirect } from "next/navigation";
import { fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { getInboxCount } from "@/lib/inkorg-server";
import { Masthead } from "@/components/shell/Masthead";
import {
  currentRoundYear,
  fmtDate,
  todayStockholm,
  type MyReport,
  type Round,
} from "./lib";
import styles from "./arsrapport.module.css";

export const dynamic = "force-dynamic";

export default async function ArsrapportIndex() {
  const user = await requireUser();
  const { reports } = await fetchApi<{ reports: MyReport[] }>(
    "/v2/arsrapport/mina",
  );
  // Exactly one report and no genebank role: straight to it.
  const manages = user.is_admin || (user.is_manager?.length ?? 0) > 0;
  if (reports.length === 1 && !manages)
    redirect(`/stamboken/arsrapport/${reports[0].herd}/${reports[0].year}`);

  // Managers reach the status view of the current round, which may not exist yet (a helper's route is the queue).
  const rounds = manages
    ? (await fetchApi<{ rounds: Round[] }>("/v2/arsrapport/rundor")).rounds
    : [];
  const statusYear = currentRoundYear(rounds, todayStockholm());
  const showInbox =
    reports.length === 0 &&
    !user.is_owner?.length &&
    (await getInboxCount()
      .then((c) => c.works_in_queue)
      .catch(() => false));

  return (
    <>
      <Masthead eyebrow="Min besättning" title="Årsrapport" />
      <div className={styles.root}>
        {manages && (
          <Link
            className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
            href={`/stamboken/arsrapport/status/${statusYear}`}
          >
            Status för genbanken, runda {statusYear}
          </Link>
        )}
        {showInbox ? (
          <>
            <p>
              Du har inga egna besättningar. Årsrapporter som kommer in på
              papper registrerar du i Inkorgen.
            </p>
            <Link href="/stamboken/inkorg">Till Inkorgen</Link>
          </>
        ) : reports.length === 0 ? (
          <p>Ingen årsrapport är öppen för dina besättningar ännu.</p>
        ) : (
          <ul className={styles.cardList}>
            {reports.map((r) => (
              <li key={`${r.herd}-${r.year}`}>
                <Link
                  className={styles.cardLink}
                  href={`/stamboken/arsrapport/${r.herd}/${r.year}`}
                >
                  <strong>
                    {r.herd}, årsrapport {r.year}
                  </strong>
                  <br />
                  {r.status === "submitted" ? "Inskickad" : "Inte inskickad"}
                  {r.deadline
                    ? ` · sista dag för stödet ${fmtDate(r.deadline)}`
                    : ""}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>
    </>
  );
}
