import Link from "next/link";
import { notFound } from "next/navigation";
import { ApiError, fetchApi } from "@/lib/api";
import { requireUser } from "@/lib/auth";
import {
  fetchHandlers,
  getInboxCount,
  requireQueueWorker,
} from "@/lib/inkorg-server";
import { NO_INBOX } from "@/lib/inkorg";
import { RefreshBadge } from "@/components/shell/RefreshBadge";
import { Masthead } from "@/components/shell/Masthead";
import type { ColorOption } from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";
import type { GenebankHerd } from "@/utils/saleRules";
import {
  colorNamesFor,
  lacksRole,
  STATE_LABEL,
  type InboxDetail,
  type QueueList,
} from "../lib";
import { WorkView } from "./WorkView";

export const dynamic = "force-dynamic";

export default async function InkorgItemPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  if (!/^\d+$/.test(id)) notFound();
  const user = await requireUser();
  await requireQueueWorker();
  // Opening the item marks its notices read after the layout counted them.
  const { unread } = await getInboxCount().catch(() => NO_INBOX);
  let item: InboxDetail;
  try {
    // Logged by the API as "oppnad", and reads the caller's notices of the item.
    item = await fetchApi<InboxDetail>(`/v2/inkorg/${id}`);
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e;
  }
  const [colors, genebanks, herds, handlers, myGenebanks] = await Promise.all([
    fetchApi<Record<string, ColorOption[]>>("/colors").catch(() => null),
    fetchApi<{ genebanks: { id: number; name: string }[] }>("/genebanks")
      .then((r) => r.genebanks)
      .catch(() => []),
    item.genebank_id
      ? fetchApi<{ herds: GenebankHerd[] }>(
          `/v2/genebank/${item.genebank_id}/herds`,
        )
          .then((r) => r.herds)
          .catch(() => [])
      : Promise.resolve([]),
    fetchHandlers(),
    // The cheapest place for the user's genebanks: the list answers with them.
    fetchApi<QueueList>("/v2/inkorg?limit=1")
      .then((r) => r.my_genebanks ?? null)
      .catch(() => null),
  ]);
  // The colour list of the item's genebank, not of its herd: it may have none.
  const colorNames = colorNamesFor(
    colors,
    genebanks.find((g) => g.id === item.genebank_id)?.name,
  );

  return (
    <>
      <RefreshBadge unread={unread} />
      <Masthead
        eyebrow="Inkorg"
        title={`Ärende ${item.id}`}
        meta={`${item.herd ?? "Okänd besättning"} · ${STATE_LABEL[item.state] ?? item.state}`}
        actions={
          <Link
            href="/stamboken/inkorg"
            className="sb-btn sb-btn-secondary sb-btn-sm"
          >
            Till kön
          </Link>
        }
      />
      <WorkView
        item={item}
        user={{
          id: user.id,
          is_admin: user.is_admin,
          is_manager: user.is_manager,
        }}
        noRole={lacksRole(
          { id: user.id, is_admin: user.is_admin, is_manager: user.is_manager },
          item.genebank_id,
          myGenebanks,
        )}
        colors={colorNames}
        herds={herds}
        people={handlers}
      />
    </>
  );
}
