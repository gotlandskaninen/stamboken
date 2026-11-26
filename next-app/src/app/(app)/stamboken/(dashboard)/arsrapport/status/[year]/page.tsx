import { Suspense } from "react";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import { ApiError, fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { requireQueueWorker } from "@/lib/inkorg-server";
import { MODE_COOKIE, parseMode } from "@/lib/mode";
import { Masthead } from "@/components/shell/Masthead";
import { manages, type QueueList } from "../../../inkorg/lib";
import {
  defaultRoundDates,
  parseFilter,
  regularRoundYear,
  todayStockholm,
  type Round,
  type StatusView,
} from "../../lib";
import styles from "../../arsrapport.module.css";
import inkorg from "../../../inkorg/inkorg.module.css";
import { BlankFormLink, StatusTable } from "./StatusTable";
import { RoundPanel } from "./RoundPanel";
import { StatusSwitch } from "./StatusSwitch";

export const dynamic = "force-dynamic";

async function BlankForm({ check }: { check: Promise<boolean> }) {
  return <BlankFormLink available={await check} />;
}

type Switch = {
  year: number;
  genebankId: number;
  genebanks: { id: number; name: string }[];
};

// The rounds there are, the regular year's (which may not exist yet, also while an older round is open) and
// this page's.
async function YearSwitch({
  rounds,
  today,
  ...props
}: Switch & { rounds: Promise<Round[]>; today: string }) {
  const list = await rounds;
  const years = [
    ...new Set([
      ...list.map((r) => r.year),
      regularRoundYear(list, today),
      props.year,
    ]),
  ].sort((a, b) => b - a);
  return <StatusSwitch {...props} years={years} />;
}

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

  // Ops puts the blank form on the server (docs/arsrapport.md); until then the link would open a 404. Only a
  // confirmed 404 hides the link. Awaited inside its own Suspense, so a slow check does not hold up the table.
  const blankFormCheck = fetchApi("/v2/arsrapport/blankett.pdf", {
    method: "HEAD",
    timeout: 3000,
  }).then(
    () => true,
    (e) => !(e instanceof ApiError && e.status === 404),
  );
  // Only the switch needs the rounds, inside its own Suspense: without them it offers the page's year.
  const rounds = fetchApi<{ rounds: Round[] }>("/v2/arsrapport/rundor").then(
    (r) => r.rounds,
    () => [] as Round[],
  );
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
  const today = todayStockholm();
  const switchProps = {
    year: Number(year),
    genebankId: genebank.id,
    genebanks: options,
  };

  // 404: the year has no round yet. The panel offers to create it.
  let view: StatusView | null = null;
  try {
    view = await fetchApi<StatusView>(
      `/v2/arsrapport/${year}/status?genebank_id=${genebank.id}`,
    );
  } catch (e) {
    if (!(e instanceof ApiError && e.status === 404)) throw e;
  }
  const activation = view?.round.genebanks.find(
    (g) => g.genebank_id === genebank.id,
  );
  // A round that closed without being activated here (the old app's rounds): nothing to report or show. A legacy
  // round can lack its end date; the default's then counts.
  const closed =
    !!view &&
    !activation &&
    (view.round.end_date ?? defaultRoundDates(Number(year)).end_date) < today;

  // How many invitations go out, while none has: counts only, readable by helpers too.
  const recipients =
    view && !closed && !activation?.sent_at
      ? await fetchApi<{ med_epost: number; utan_epost: number }>(
          `/v2/arsrapport/rundor/${year}/genbanker/${genebank.id}/mottagare`,
        )
      : null;

  return (
    <>
      <Masthead
        eyebrow="Årsrapport"
        title={`Status ${year}`}
        meta={`${genebank.name}${view && !closed ? ` · ${view.rows.length} besättningar` : ""}`}
        actions={
          <div className={styles.mastActions}>
            <Suspense
              key={`${genebank.id}-${year}`} // Back to another genebank keeps this page mounted: start from its choice
              fallback={
                <StatusSwitch {...switchProps} years={[Number(year)]} />
              }
            >
              <YearSwitch {...switchProps} rounds={rounds} today={today} />
            </Suspense>
            <Suspense fallback={null}>
              <BlankForm check={blankFormCheck} />
            </Suspense>
          </div>
        }
      />
      <div className={`${inkorg.container} ${styles.statusContainer}`}>
        <RoundPanel
          key={`${genebank.id}-${env}-${view?.round.start_date}-${view?.round.deadline}-${view?.round.end_date}`}
          year={Number(year)}
          genebankId={genebank.id}
          genebankName={genebank.name}
          round={view?.round ?? null}
          closed={closed}
          canEdit={canEdit}
          recipients={recipients}
          env={env}
        />
        {view && !closed && (
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
