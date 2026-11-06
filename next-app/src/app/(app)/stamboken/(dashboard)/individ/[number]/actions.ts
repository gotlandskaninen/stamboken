"use server";
import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";
import type { GenebankHerd } from "@/utils/saleRules";

interface Individual {
  id: number;
  number: string;
  name: string | null;
  genebank_id: number;
  [key: string]: unknown;
}

export async function updateIndividual(
  number: string,
  data: Record<string, unknown>,
) {
  try {
    const updated = await fetchApi<Individual>(
      `/individual/${encodeURIComponent(number)}`,
      {
        method: "PATCH",
        body: JSON.stringify(data),
      },
    );
    revalidatePath(`/stamboken/individ/${number}`);
    return { success: true as const, individual: updated };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false as const, error: e.detail };
    }
    // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring
    console.error("updateIndividual failed:", number, e);
    return { success: false as const, error: "unexpected_error" };
  }
}

/** Herds of a genebank (code + name only) — picker data for "Sälj". */
export async function getGenebankHerds(genebankId: number) {
  try {
    const data = await fetchApi<{ herds: GenebankHerd[] }>(
      `/v2/genebank/${genebankId}/herds`,
    );
    return { success: true as const, herds: data.herds };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false as const, error: e.detail };
    }
    // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring
    console.error("getGenebankHerds failed:", genebankId, e);
    return { success: false as const, error: "unexpected_error" };
  }
}

type HtActionResult =
  | { success: true }
  | { success: false; error: string; rows?: number[] };

function htFailure(
  e: unknown,
  label: string,
  ...context: unknown[]
): HtActionResult {
  if (e instanceof ApiError) {
    // A 409 names the conflicting rows; pass their ids on so the
    // correction dialog can add them to the same correction.
    const rows = Array.isArray(e.extensions.rows)
      ? e.extensions.rows
          .map((r) => (r as { id?: unknown })?.id)
          .filter((id): id is number => typeof id === "number")
      : [];
    return rows.length
      ? { success: false, error: e.detail, rows }
      : { success: false, error: e.detail };
  }
  // nosemgrep: javascript.lang.security.audit.unsafe-formatstring.unsafe-formatstring
  console.error(`${label} failed:`, ...context, e);
  return { success: false, error: "unexpected_error" };
}

/** Void one herd-tracking row — also "Ångra försäljning" (spec 999.5). */
export async function voidHerdTracking(
  number: string,
  htId: number,
  reason: string,
  operationId: string,
): Promise<HtActionResult> {
  try {
    await fetchApi(`/v2/herd-tracking/${htId}/void`, {
      method: "POST",
      body: JSON.stringify({ reason, operation_id: operationId }),
    });
    revalidatePath(`/stamboken/individ/${number}`);
    return { success: true };
  } catch (e) {
    return htFailure(e, "voidHerdTracking", number, htId);
  }
}

/** Manager correction. */
export async function correctHerdTracking(
  number: string,
  payload: {
    operation_id: string;
    void_ids: number[];
    events: unknown[];
    reason: string;
  },
): Promise<HtActionResult> {
  try {
    await fetchApi(
      `/v2/individual/${encodeURIComponent(number)}/herd-tracking/corrections`,
      {
        method: "POST",
        body: JSON.stringify(payload),
      },
    );
    revalidatePath(`/stamboken/individ/${number}`);
    return { success: true };
  } catch (e) {
    return htFailure(e, "correctHerdTracking", number);
  }
}

/** Undo a whole herd-tracking operation (manager/admin). */
export async function undoHerdTrackingOperation(
  number: string,
  operationId: string,
  reason: string,
  undoOperationId: string,
): Promise<HtActionResult> {
  try {
    const data = await fetchApi<{ individuals?: { number: string }[] }>(
      `/v2/herd-tracking/operations/${encodeURIComponent(operationId)}/undo`,
      {
        method: "POST",
        body: JSON.stringify({ reason, operation_id: undoOperationId }),
      },
    );
    // An operation can span several rabbits (bulk attestations).
    const numbers = new Set([
      number,
      ...(data?.individuals ?? []).map((i) => i.number),
    ]);
    for (const n of numbers) revalidatePath(`/stamboken/individ/${n}`);
    return { success: true };
  } catch (e) {
    return htFailure(e, "undoHerdTrackingOperation", number, operationId);
  }
}
