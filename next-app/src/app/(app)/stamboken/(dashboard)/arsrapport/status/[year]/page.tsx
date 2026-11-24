import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { ApiError, fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { requireQueueWorker } from "@/lib/inkorg-server";
import { MODE_COOKIE, parseMode } from "@/lib/mode";
import { Masthead } from "@/components/shell/Masthead";
import { manages, type QueueList } from "../../../inkorg/lib";
import { parseFilter, type StatusView } from "../../lib";
import styles from "../../arsrapport.module.css";
import inkorg from "../../../inkorg/inkorg.module.css";
import { BlankFormLink, StatusTable } from "./StatusTable";
import { RoundPanel } from "./RoundPanel";

export const dynamic = "force-dynamic";

export default async function StatusPage({
  params,
  searchParams,
}: {
  params: Promise<{ year: string }>;
  searchParams: Promise<{ genebank_id?: string; filter?: string }>;
}) {
  const [{ year }, sp] = await Promise.all([params, searchParams]);
  if (!/^\d{4}$/.test(year)) notFound();
  const user = await requireUser();
  await requireQueueWorker();
  const env = parseMode((await cookies()).get(MODE_COOKIE)?.value);

  // The genebanks the user may open: admin all, others where they manage or help.
  const [queue, all] = await Promise.all([
    fetchApi<QueueList>("/v2/inkorg?limit=1"),
    fetchApi<{ genebanks: { id: number; name: string }[] }>("/genebanks").then(
      (r) => r.genebanks ?? [],
    ),
  ]);
  const mine = queue.my_genebanks ?? [];
  const options = user.is_admin
    ? all
    : mine.map((id) => ({
        id,
        name: all.find((g) => g.id === id)?.name ?? `Genbank ${id}`,
      }));
  const wanted = Number(sp.genebank_id);
  // Default: the first genebank the user manages, else the first readable one.
  const managed = options.find((g) => manages(user, g.id) && !user.is_admin);
  const genebank =
    options.find((g) => g.id === wanted) ?? managed ?? options[0];
  if (!genebank) notFound();
  const canEdit = manages(user, genebank.id);

  // 404: the year has no round yet. The panel offers to create it.
  let view: StatusView | null = null;
  try {
    view = await fetchApi<StatusView>(
      `/v2/arsrapport/${year}/status?genebank_id=${genebank.id}`,
    );
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 404)) throw e;
  }

  // How many invitations go out, while none has: counts only, readable by helpers too.
  const sent = view?.round.genebanks.find(
    (g) => g.genebank_id === genebank.id,
  )?.sent_at;
  const recipients =
    view && !sent
      ? await fetchApi<{ med_epost: number; utan_epost: number }>(
          `/v2/arsrapport/rundor/${year}/genbanker/${genebank.id}/mottagare`,
        )
      : null;

  return (
    <>
      <Masthead
        eyebrow="Årsrapport"
        title={`Status ${year}`}
        meta={`${genebank.name}${view ? ` · ${view.rows.length} besättningar` : ""}`}
        actions={
          <div className={inkorg.row}>
            {options.length > 1 && (
              <form method="get" className={inkorg.row}>
                <label>
                  Genbank{" "}
                  <select
                    name="genebank_id"
                    defaultValue={genebank.id}
                    className={`sb-input ${styles.field}`}
                  >
                    {options.map((g) => (
                      <option key={g.id} value={g.id}>
                        {g.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  type="submit"
                  className={`sb-btn sb-btn-secondary ${styles.btn} ${styles.secondary}`}
                >
                  Visa
                </button>
              </form>
            )}
            <BlankFormLink />
          </div>
        }
      />
      <div className={inkorg.container}>
        <RoundPanel
          key={`${genebank.id}-${env}-${view?.round.start_date}-${view?.round.deadline}-${view?.round.end_date}`}
          year={Number(year)}
          genebankId={genebank.id}
          genebankName={genebank.name}
          round={view?.round ?? null}
          canEdit={canEdit}
          recipients={recipients}
          env={env}
        />
        {view && (
          <StatusTable
            key={`${genebank.id}-${env}`}
            view={view}
            year={Number(year)}
            genebankId={genebank.id}
            filter={parseFilter(sp.filter)}
            canEdit={canEdit}
            env={env}
          />
        )}
      </div>
    </>
  );
}
