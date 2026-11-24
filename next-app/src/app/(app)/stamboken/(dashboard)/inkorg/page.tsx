import Link from "next/link";
import { ApiError, fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { formatTime } from "@/lib/inkorg";
import { fetchHandlers, requireQueueWorker } from "@/lib/inkorg-server";
import { GmailAlarm } from "./GmailAlarm";
import { QueueBrowser } from "./QueueBrowser";
import { AssignHerd } from "./QueueControls";
import {
  manages,
  people,
  QUEUE_MODES,
  type QueueMode,
  type QueueList,
} from "./lib";
import styles from "./inkorg.module.css";

export const dynamic = "force-dynamic";

export default async function InkorgPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const user = await requireUser();
  await requireQueueWorker();
  const sp = Object.fromEntries(
    Object.entries(await searchParams).map(([key, value]) => [
      key,
      Array.isArray(value) ? value[0] : value,
    ]),
  );
  const filters = new URLSearchParams();
  if (sp.scope) filters.set("scope", sp.scope);
  if (QUEUE_MODES.includes(sp.mode as QueueMode) && sp.mode !== "oppna")
    filters.set("mode", sp.mode!);
  if (sp.herd?.trim()) filters.set("herd", sp.herd.trim().toUpperCase());
  if (sp.order === "newest") filters.set("order", sp.order);
  if (/^[1-9]\d*$/.test(sp.offset ?? "")) filters.set("offset", sp.offset!);
  const selected = /^[1-9]\d*$/.test(sp.arende ?? "")
    ? Number(sp.arende)
    : null;
  const api = new URLSearchParams(filters);
  if (filters.has("herd")) {
    api.set("herd_prefix", filters.get("herd")!);
    api.delete("herd");
  }
  api.set("limit", "50");

  let data: QueueList;
  try {
    data = await fetchApi<QueueList>(`/v2/inkorg?${api}`);
  } catch (error) {
    if (!(error instanceof ApiError) || error.status !== 400) throw error;
    return (
      <div className={styles.container}>
        <h1>Inkorg</h1>
        <p role="alert">{error.detail}</p>
        <Link href="/stamboken/inkorg">Visa alla öppna</Link>
      </div>
    );
  }
  const canAssign = manages(user, null);
  const handlers = canAssign
    ? people(
        { id: user.id, name: user.fullname || `Konto ${user.id}` },
        data.items,
        await fetchHandlers(),
      )
    : [];
  const reading = data.interpretation;
  return (
    <div className={styles.inbox}>
      <header className={styles.inboxHeader}>
        <h1>Inkorg</h1>
        {reading && reading.interpreter !== "av" && (
          <p>
            Bildtolkning: {reading.waiting}{" "}
            {reading.waiting === 1 ? "foto väntar" : "foton väntar"}.
            {reading.last_done_at &&
              ` Senast klar ${formatTime(reading.last_done_at)}.`}
          </p>
        )}
      </header>
      <GmailAlarm />
      {reading?.alarm && (
        <p role="alert" className={styles.error}>
          Tre foton i rad gick inte att tolka. Kontrollera att bildtolkningen är
          igång.
        </p>
      )}
      <QueueBrowser
        data={data}
        query={filters.toString()}
        selected={selected}
        userId={user.id}
        now={Date.now()}
        assignment={canAssign && <AssignHerd people={handlers} />}
      >
        {selected ? (
          <Link
            href={`/stamboken/inkorg/${selected}`}
            prefetch={false}
            className="sb-btn"
          >
            Öppna ärende {selected}
          </Link>
        ) : (
          <p className={styles.muted}>Välj ett ärende i listan.</p>
        )}
      </QueueBrowser>
    </div>
  );
}
