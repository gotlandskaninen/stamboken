"use server";
import { revalidatePath } from "next/cache";
import { fetchApi, ApiError } from "@/lib/api";
import type { AuditLogEntry } from "@/app/(app)/stamboken/(dashboard)/individ/[number]/audit-types";

interface Breeding {
  id: number;
  mother: string;
  father: string;
  breeding_herd: string;
  breed_date: string | null;
  birth_date: string | null;
  [key: string]: unknown;
}

interface Herd {
  herd: string;
  herd_name: string;
  [key: string]: unknown;
}

type ActionResult<T = void> =
  | { success: true; data: T }
  | { success: false; error: string };

export async function registerBreeding(data: {
  mother: string;
  father: string;
  date: string;
  notes?: string;
  breeding_herd: string;
}): Promise<ActionResult<Breeding>> {
  try {
    const breeding = await fetchApi<Breeding>("/v2/breeding", {
      method: "POST",
      body: JSON.stringify(data),
    });
    revalidatePath("/stamboken/min-besattning");
    return { success: true, data: breeding };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    console.error("registerBreeding failed:", e);
    return { success: false, error: "unexpected_error" };
  }
}

export async function registerBirth(
  breedingId: number,
  data: {
    date: string;
    litter_size: number;
    litter_size6w?: number | null;
    notes?: string;
  },
): Promise<ActionResult<Breeding>> {
  try {
    const breeding = await fetchApi<Breeding>(
      `/v2/breeding/${breedingId}/birth`,
      {
        method: "POST",
        body: JSON.stringify(data),
      },
    );
    revalidatePath("/stamboken/min-besattning");
    return { success: true, data: breeding };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    console.error("registerBirth failed:", e);
    return { success: false, error: "unexpected_error" };
  }
}

export async function updateBreeding(
  breedingId: number,
  data: Record<string, unknown>,
): Promise<ActionResult<Breeding>> {
  try {
    const breeding = await fetchApi<Breeding>(`/v2/breeding/${breedingId}`, {
      method: "PATCH",
      body: JSON.stringify(data),
    });
    revalidatePath("/stamboken/min-besattning");
    return { success: true, data: breeding };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    console.error("updateBreeding failed:", e);
    return { success: false, error: "unexpected_error" };
  }
}

export async function deleteBreeding(
  breedingId: number,
): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/breeding/${breedingId}`, {
      method: "DELETE",
    });
    revalidatePath("/stamboken/min-besattning");
    return { success: true, data: undefined };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    console.error("deleteBreeding failed:", e);
    return { success: false, error: "unexpected_error" };
  }
}

export async function updateHerd(
  herdId: string,
  data: Record<string, unknown>,
): Promise<ActionResult<Herd>> {
  try {
    const herd = await fetchApi<Herd>(
      `/v2/herd/${encodeURIComponent(herdId)}`,
      {
        method: "PATCH",
        body: JSON.stringify(data),
      },
    );
    revalidatePath("/stamboken/min-besattning");
    return { success: true, data: herd };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    console.error("updateHerd failed:", e);
    return { success: false, error: "unexpected_error" };
  }
}

/** The litter of a registration: an existing one, or ("Lägg till kanin") the
 *  parents and birth of a litter the API reuses or creates. */
export type RegisterLitter =
  | { breeding_id: number }
  | { mother: string; father: string; birth_date: string; litter_size: number };

// The API's certificate_error is an RFC-9457 dict; the dialogs show a string.
function problemText(raw: unknown): string | null {
  if (typeof raw === "object" && raw !== null) {
    const p = raw as { detail?: string; title?: string };
    return p.detail ?? p.title ?? JSON.stringify(raw);
  }
  return (raw as string | null) ?? null;
}

/** The paper certificate's individual number against Stamboken's (POST
 *  /v2/individual/number-check, and the 409 number_conflict of a registration). */
export interface NumberCheckHolder {
  number: string | null;
  herd: string;
  breeding_id: number | null;
  litter_number: number | null;
  litter: string | null;
  contactable?: boolean;
}

export interface NumberCheck {
  stamboken_number: string | null;
  paper_number: string;
  status: "match" | "conflict" | "uncomputable";
  conflicts: {
    kind: string;
    paper: string | null;
    stamboken: string | null;
    holder: NumberCheckHolder | null;
  }[];
  choices: ("use_stamboken_number" | "paper_is_right")[];
  actions: {
    kind: string;
    text: string;
    self_service: string | null;
    manager_message: string | null;
  }[];
}

/** The breeder's choice after a number conflict, sent with the registration again. */
export interface NumberResolution {
  expected_number: string | null;
  choice: "use_stamboken_number" | "paper_is_right";
}

// A 409 number_conflict carries the dry-run fields; its status is check_status.
function numberConflict(e: ApiError): NumberCheck | undefined {
  if (e.status !== 409 || e.title !== "number_conflict") return undefined;
  const { check_status, ...fields } = e.extensions as Record<string, unknown>;
  return {
    ...(fields as Omit<NumberCheck, "status">),
    status: check_status as NumberCheck["status"],
  };
}

export async function checkIndividualNumber(
  data: (
    | { breeding_id: number }
    | { mother: string; father: string; birth_date: string }
  ) & { paper_number: string; paper_certificate?: string },
): Promise<ActionResult<NumberCheck>> {
  try {
    const result = await fetchApi<NumberCheck>("/v2/individual/number-check", {
      method: "POST",
      body: JSON.stringify(data),
    });
    return { success: true, data: result };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    console.error("checkIndividualNumber failed:", e);
    return { success: false, error: "unexpected_error" };
  }
}

export async function registerIndividual(
  data: RegisterLitter & {
    sex: string | null;
    color: string;
    name?: string;
    color_note?: string;
    eye_color?: string;
    claw_color?: string;
    belly_color?: string;
    hair_notes?: string;
    certificate_type: "paper" | "digital";
    paper_certificate?: string;
    paper_number?: string;
    resolution?: NumberResolution;
    litter_size6w?: number | null;
    position?: number | null;
  },
): Promise<
  | {
      success: true;
      data: {
        individual: Record<string, unknown>;
        certificate: string | null;
        certificate_error: string | null;
      };
    }
  | { success: false; error: string; numberCheck?: NumberCheck }
> {
  try {
    const result = await fetchApi<{
      individual: Record<string, unknown>;
      certificate: string | null;
      certificate_error: unknown;
    }>("/v2/individual", {
      method: "POST",
      body: JSON.stringify(data),
    });
    revalidatePath("/stamboken/min-besattning");
    return {
      success: true,
      data: {
        ...result,
        certificate_error: problemText(result.certificate_error),
      },
    };
  } catch (e) {
    if (e instanceof ApiError) {
      return {
        success: false,
        error: e.detail,
        numberCheck: numberConflict(e),
      };
    }
    console.error("registerIndividual failed:", e);
    return { success: false, error: "unexpected_error" };
  }
}

export interface IndividualNumberSuggestion {
  suggested: string | null;
  suggested_position: number | null;
  used_positions: number[];
  available_positions: number[];
  current_count: number;
  max_count: number;
  limited_by: "ceiling" | "litter_size";
  can_register: boolean;
  certified_count: number;
  certified_max_count: number | null;
  past_6w: boolean;
  can_issue_certificate: boolean;
  certificate_blocked_reason:
    | "litter_size6w_required"
    | "certificate_quota_exceeded"
    | null;
  /** The litter the number belongs to; null for a litter not created yet. */
  breeding_id: number | null;
  litter_number: number | null;
}

export async function suggestIndividualNumber(
  litter: number | { mother: string; father: string; birth_date: string },
): Promise<
  | { success: true; data: IndividualNumberSuggestion }
  | { success: false; error: string; errorTitle?: string }
> {
  const query =
    typeof litter === "number"
      ? new URLSearchParams({ breeding_id: String(litter) })
      : new URLSearchParams(litter);
  try {
    const result = await fetchApi<IndividualNumberSuggestion>(
      `/v2/individual/suggest-number?${query}`,
    );
    return { success: true, data: result };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail, errorTitle: e.title };
    }
    console.error("suggestIndividualNumber failed:", e);
    return { success: false, error: "unexpected_error" };
  }
}

export async function checkLitterOrder(
  herd: string,
  year: number,
): Promise<
  ActionResult<{ consistent: boolean; conflicts: Record<string, unknown>[] }>
> {
  try {
    const result = await fetchApi<{
      consistent: boolean;
      conflicts: Record<string, unknown>[];
    }>(
      `/v2/breeding/check-order?herd=${encodeURIComponent(herd)}&year=${year}`,
    );
    return { success: true, data: result };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    return { success: false, error: "unexpected_error" };
  }
}

export type RenumberActionResult =
  | { success: true; data: { changes: Record<string, unknown>[] } }
  | { success: false; error: string; errorStatus?: number };

export async function renumberLitters(
  herdId: string,
  year: number,
  confirm: boolean,
): Promise<RenumberActionResult> {
  try {
    const result = await fetchApi<{ changes: Record<string, unknown>[] }>(
      "/v2/breeding/renumber",
      {
        method: "POST",
        body: JSON.stringify({ herd_id: herdId, year, confirm }),
      },
    );
    if (confirm) {
      revalidatePath("/stamboken/min-besattning");
    }
    return { success: true, data: result };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail, errorStatus: e.status };
    }
    return { success: false, error: "unexpected_error" };
  }
}

// ── Litter roster (Phase 15) ─────────────────────────────────────────────────

export interface RosterBunny {
  id: number;
  breeding_id: number;
  slot_order: number;
  observed_sex: string | null;
  observed_color: string | null;
  label: string | null;
  notes: string | null;
  fate:
    | "undecided"
    | "kept_unregistered"
    | "sold_unregistered"
    | "culled"
    | "died";
  provisional_number: string | null;
  individual: Record<string, unknown> | null;
}

export async function getLitterRoster(
  breedingId: number,
): Promise<ActionResult<RosterBunny[]>> {
  try {
    const result = await fetchApi<{ roster: RosterBunny[] }>(
      `/v2/breeding/${breedingId}/roster`,
    );
    return { success: true, data: result.roster };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    return { success: false, error: "unexpected_error" };
  }
}

export async function addBunnies(
  breedingId: number,
  count?: number,
  fields?: {
    observed_sex?: string;
    observed_color?: string;
    label?: string;
    notes?: string;
  },
): Promise<ActionResult<RosterBunny[]> & { errorTitle?: string }> {
  try {
    const result = await fetchApi<{ bunnies: RosterBunny[] }>(
      `/v2/breeding/${breedingId}/bunnies`,
      {
        method: "POST",
        body: JSON.stringify({ count, ...fields }),
      },
    );
    revalidatePath("/stamboken/min-besattning");
    return { success: true, data: result.bunnies ?? [] };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail, errorTitle: e.title };
    }
    return { success: false, error: "unexpected_error" };
  }
}

export async function getAuditHistory(
  tableName: string,
  recordId: number,
): Promise<AuditLogEntry[]> {
  try {
    const result = await fetchApi<{ status: string; data: AuditLogEntry[] }>(
      `/audit-log/${tableName}/${recordId}`,
    );
    return result.data ?? [];
  } catch {
    // 403 for non-managers — the history section simply stays hidden
    return [];
  }
}

export async function deleteBunny(bunnyId: number): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/bunny/${bunnyId}`, { method: "DELETE" });
    revalidatePath("/stamboken/min-besattning");
    return { success: true, data: undefined };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    return { success: false, error: "unexpected_error" };
  }
}

export async function reorderRoster(
  breedingId: number,
  order: number[],
): Promise<ActionResult<RosterBunny[] | null>> {
  try {
    const result = await fetchApi<{ roster: RosterBunny[] }>(
      `/v2/breeding/${breedingId}/roster/reorder`,
      {
        method: "POST",
        body: JSON.stringify({ order }),
      },
    );
    return {
      success: true,
      data: Array.isArray(result?.roster) ? result.roster : null,
    };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    return { success: false, error: "unexpected_error" };
  }
}

export async function patchBunny(
  bunnyId: number,
  fields: {
    observed_sex?: string | null;
    observed_color?: string | null;
    label?: string | null;
    notes?: string | null;
    slot_order?: number;
    fate?:
      | "undecided"
      | "kept_unregistered"
      | "sold_unregistered"
      | "culled"
      | "died";
  },
): Promise<ActionResult<Record<string, unknown>>> {
  try {
    const result = await fetchApi<Record<string, unknown>>(
      `/v2/bunny/${bunnyId}`,
      {
        method: "PATCH",
        body: JSON.stringify(fields),
      },
    );
    revalidatePath("/stamboken/min-besattning");
    return { success: true, data: result };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    return { success: false, error: "unexpected_error" };
  }
}

export interface PromotePayload {
  certificate_type: "paper" | "digital";
  paper_certificate?: string;
  paper_number?: string;
  resolution?: NumberResolution;
  litter_size6w?: number;
  sex?: string;
  name?: string;
  color?: string;
  color_note?: string;
  eye_color?: string;
  claw_color?: string;
  belly_color?: string;
  hair_notes?: string;
}

export interface PromoteResult {
  individual: Record<string, unknown>;
  certificate: string | null;
  certificate_error: string | null;
}

export type PromoteActionResult =
  | { success: true; data: PromoteResult }
  | {
      success: false;
      error: string;
      errorTitle?: string;
      numberCheck?: NumberCheck;
    };

export async function promoteBunny(
  bunnyId: number,
  payload: PromotePayload,
): Promise<PromoteActionResult> {
  try {
    const resp = await fetchApi<{
      individual: Record<string, unknown>;
      certificate: string | null;
      certificate_error: unknown;
    }>(`/v2/bunny/${bunnyId}/promote`, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    revalidatePath("/stamboken/min-besattning");
    return {
      success: true,
      data: {
        individual: resp.individual,
        certificate: resp.certificate,
        certificate_error: problemText(resp.certificate_error),
      },
    };
  } catch (e) {
    if (e instanceof ApiError) {
      return {
        success: false,
        error: e.detail,
        errorTitle: e.title,
        numberCheck: numberConflict(e),
      };
    }
    return { success: false, error: "unexpected_error" };
  }
}

export interface ColorOption {
  id: number;
  name: string;
  comment: string | null;
}

export async function getColors(): Promise<Record<
  string,
  ColorOption[]
> | null> {
  try {
    return await fetchApi<Record<string, ColorOption[]>>("/colors");
  } catch {
    return null;
  }
}

export async function unpromoteBunny(bunnyId: number): Promise<ActionResult> {
  try {
    await fetchApi(`/v2/bunny/${bunnyId}/unpromote`, {
      method: "POST",
    });
    revalidatePath("/stamboken/min-besattning");
    return { success: true, data: undefined };
  } catch (e) {
    if (e instanceof ApiError) {
      return { success: false, error: e.detail };
    }
    return { success: false, error: "unexpected_error" };
  }
}
