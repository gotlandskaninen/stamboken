import { Suspense } from "react";
import { notFound } from "next/navigation";
import { fetchApi, ApiError } from "@/lib/api";
import type { Individual, PedigreeNode } from "@/redux/api/apiSlice";
import type { HerdTrackingHistory } from "@/lib/herdTracking";
import type { AuditLogResponse } from "./audit-types";
import {
  IndividualGenetics,
  GeneticsSkeleton,
} from "@/components/individual/IndividualGenetics";
import { IndividualDetail } from "./individual-detail";

export const dynamic = "force-dynamic"; // Never statically generate — user-specific data

export default async function IndividualPage({
  params,
}: {
  params: Promise<{ number: string }>;
}) {
  const { number } = await params;
  // Auth is handled by (dashboard)/layout.tsx — requireUser() runs there.
  // v2 GET returns RFC 9457 404 for missing individuals.
  // Use 30s timeout — dev-mode compilation can be slow on first load.
  let individual: Individual;
  try {
    individual = await fetchApi<Individual>(
      `/v2/individual/${encodeURIComponent(number)}`,
      { timeout: 30000 },
    );
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) notFound();
    throw e; // 500s, timeouts, etc. → error.tsx boundary
  }

  // Pedigree tree — fails gracefully (403/500 → null)
  const pedigreeData = await fetchApi<PedigreeNode>(
    `/individual/${encodeURIComponent(number)}/pedigree?generations=4`,
  ).catch(() => null);

  const [history, auditData] = await Promise.all([
    // Herd-tracking history (spec 999.5) — voided rows included; the section's
    // "Visa ångrade" toggle decides what is shown. Fails gracefully (null).
    fetchApi<HerdTrackingHistory>(
      `/v2/individual/${encodeURIComponent(number)}/herd-tracking?include_voided=1`,
    ).catch(() => null),
    // Audit history — manager/admin only, fails gracefully for non-managers (403 → null)
    fetchApi<AuditLogResponse>(`/audit-log/individual/${individual.id!}`).catch(
      () => null,
    ),
  ]);

  return (
    <Suspense>
      <IndividualDetail
        individual={individual}
        pedigree={pedigreeData}
        history={history}
        auditEntries={auditData?.data ?? []}
        geneticsSlot={
          <Suspense fallback={<GeneticsSkeleton />}>
            <IndividualGenetics number={number} />
          </Suspense>
        }
      />
    </Suspense>
  );
}
