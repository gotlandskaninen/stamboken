/** Herd-tracking v2 payload (GET /api/v2/individual/<number>/herd-tracking). */
export type HerdTrackingKind =
  | "BIRTH"
  | "TRANSFER"
  | "ATTESTATION"
  | "CORRECTION";

export interface HerdRef {
  id: number | null;
  herd: string | null;
  herd_name: string | null;
  outside_genebank: boolean;
  /** Server-built display label — "Såld utanför genbanken" for GX1/MX1. */
  label: string;
}

export interface HerdTrackingRow {
  id: number;
  date: string;
  kind: HerdTrackingKind;
  herd: HerdRef;
  from_herd: HerdRef | null;
  voided_at: string | null;
  voided_reason: string | null;
  /** The operation that voided the row (null while active). */
  voided_operation_id: string | null;
  operation_id: string;
  created_at: string;
  /** null = not a Phase 10 transfer; false = registered but not confirmed by the buyer. */
  confirmed: boolean | null;
  notes: string | null;
  /** The buyer outside the association: only for admin and the genebank's managers and helpers. */
  buyer: {
    id: number;
    name: string;
    town: string;
    postal_address?: string;
    email?: string;
    phone?: string;
  } | null;
  can_void: boolean;
  can_undo_sale: boolean;
  can_undo_operation: boolean;
}

export interface HerdTrackingPeriod {
  herd: HerdRef;
  from_date: string;
  to_date: string | null;
  start_kind: HerdTrackingKind;
  start_row_id: number;
  attestation_ids: number[];
}

export interface HerdTrackingHistory {
  individual: { id: number; number: string };
  viewer: { can_manage: boolean };
  /** Server order (newest first, BIRTH first within a day) — never re-sort. */
  rows: HerdTrackingRow[];
  /** Chronological. */
  periods: HerdTrackingPeriod[];
}

export const KIND_LABELS: Record<HerdTrackingKind, string> = {
  BIRTH: "Född",
  TRANSFER: "Flytt",
  ATTESTATION: "Årsrapport",
  CORRECTION: "Korrigering",
};

export const PERIOD_START_LABELS: Record<HerdTrackingKind, string> = {
  BIRTH: "Född här",
  TRANSFER: "Flyttad hit",
  CORRECTION: "Korrigerad",
  ATTESTATION: "Rapporterad",
};

/** The newest active row, if the viewer may undo it as a sale (rows arrive newest first). */
export function latestUndoableSale(
  history: HerdTrackingHistory | null,
): HerdTrackingRow | null {
  const latest = history?.rows.find((r) => r.voided_at === null) ?? null;
  return latest?.can_undo_sale ? latest : null;
}

/** "Ångra hela åtgärden": an active row undoes its writer, a voided row the operation that voided it. */
export function undoTargetOperationId(row: HerdTrackingRow): string {
  return (row.voided_at && row.voided_operation_id) || row.operation_id;
}

/**
 * Genetics history is snapshotted on Dec 30 and never recomputed — true when
 * `date` (YYYY-MM-DD) is on or before the latest Dec 30 that is on or before `today`.
 */
export function isBeforeLatestSnapshot(
  date: string,
  today: Date = new Date(),
): boolean {
  const year = today.getFullYear();
  const thisYear = new Date(year, 11, 30);
  const latest = today >= thisYear ? thisYear : new Date(year - 1, 11, 30);
  return new Date(`${date}T00:00:00`) <= latest;
}

/** One id per dialog opening. */
export function newOperationId(): string {
  if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
  const b = crypto.getRandomValues(new Uint8Array(16));
  b[6] = (b[6] & 0x0f) | 0x40;
  b[8] = (b[8] & 0x3f) | 0x80;
  const h = Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
  return `${h.slice(0, 8)}-${h.slice(8, 12)}-${h.slice(12, 16)}-${h.slice(16, 20)}-${h.slice(20)}`;
}
