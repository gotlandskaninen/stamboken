import { cache } from "react";
import Link from "next/link";
import { ApiError, fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import { RefreshBadge } from "@/components/shell/RefreshBadge";
import {
  fetchHandlers,
  getInboxCount,
  requireQueueWorker,
} from "@/lib/inkorg-server";
import { GmailAlarm } from "./GmailAlarm";
import { CasePane } from "./CasePane";
import { InboxHeader, QueueBrowser } from "./QueueBrowser";
import { AssignHerd } from "./QueueControls";
import {
  queueHref,
  type InboxDetail,
  manages,
  people,
  QUEUE_MODES,
  type QueueMode,
  type QueueList,
} from "./lib";
import styles from "./inkorg.module.css";

export const dynamic = "force-dynamic";
const requestTime = cache(Date.now);

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
  if (selected !== null) api.set("after", String(selected));
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
  if (!data.mode_counts) {
    for (const key of ["mode", "herd", "order"]) filters.delete(key);
  }
  const query = filters.toString();
  const next = data.next_untaken?.find((id) => id !== selected);
  const nextHref = next
    ? queueHref(
        query,
        data.items.some((item) => item.id === next)
          ? { arende: next }
          : {
              mode: "nya",
              herd: null,
              order: null,
              offset: null,
              arende: next,
            },
      )
    : null;
  const canAssign = Boolean(data.mode_counts) && manages(user, null);
  const [item, handlers, count] = await Promise.all([
    selected
      ? fetchApi<InboxDetail>(`/v2/inkorg/${selected}`).catch((error) => {
          if (error instanceof ApiError && error.status === 404) return null;
          throw error;
        })
      : null,
    canAssign ? fetchHandlers() : [],
    selected ? getInboxCount() : null,
  ]);
  const pickable = people(
    { id: user.id, name: user.fullname || `Konto ${user.id}` },
    data.items,
    handlers,
  );
  const now = requestTime();
  return (
    <div className={styles.inbox}>
      {count && <RefreshBadge key={selected} unread={count.unread} />}
      <InboxHeader reading={data.interpretation} />
      <GmailAlarm />
      {data.interpretation?.alarm && (
        <p role="alert" className={styles.error}>
          Tre foton i rad gick inte att tolka. Kontrollera att bildtolkningen är
          igång.
        </p>
      )}
      <QueueBrowser
        data={data}
        query={query}
        selected={selected}
        userId={user.id}
        now={now}
        assignment={canAssign && <AssignHerd people={pickable} />}
      >
        {item ? (
          <CasePane
            key={item.id}
            item={item}
            user={{
              id: user.id,
              is_admin: user.is_admin,
              is_manager: user.is_manager,
            }}
            myGenebanks={data.my_genebanks ?? null}
            now={now}
            nextHref={nextHref}
            backHref={queueHref(query, {})}
          />
        ) : selected !== null ? (
          <div className={`sb-card ${styles.emptyList}`}>
            <p>Ärendet finns inte.</p>
            <Link
              href={queueHref(query, {})}
              className="sb-btn sb-btn-secondary"
            >
              Tillbaka till listan
            </Link>
          </div>
        ) : null}
      </QueueBrowser>
    </div>
  );
}
