import { describe, it, expect, vi, afterEach } from "vitest";
import {
  isBeforeLatestSnapshot,
  latestUndoableSale,
  newOperationId,
  undoTargetOperationId,
  type HerdTrackingHistory,
  type HerdTrackingRow,
} from "@/lib/herdTracking";

const base: HerdTrackingRow = {
  id: 1,
  date: "2025-09-30",
  kind: "TRANSFER",
  herd: {
    id: 2,
    herd: "G1300",
    herd_name: "Erikssons",
    outside_genebank: false,
    label: "G1300 – Erikssons",
  },
  from_herd: null,
  voided_at: null,
  voided_reason: null,
  voided_operation_id: null,
  operation_id: "op-1",
  created_at: "2025-09-30T10:00:00+00:00",
  confirmed: null,
  notes: null,
  buyer: null,
  can_void: true,
  can_undo_sale: true,
  can_undo_operation: false,
};
const history = (rows: HerdTrackingRow[]): HerdTrackingHistory => ({
  individual: { id: 7, number: "G1274-2501" },
  viewer: { can_manage: false },
  rows,
  periods: [],
});

describe("latestUndoableSale", () => {
  it("returns the newest active row when the server allows undoing it as a sale", () => {
    expect(latestUndoableSale(history([base]))?.id).toBe(1);
  });
  it("skips voided rows (rows arrive newest first)", () => {
    const voided = { ...base, id: 2, voided_at: "2025-10-01T08:00:00+00:00" };
    expect(latestUndoableSale(history([voided, base]))?.id).toBe(1);
  });
  it("is null when the newest active row is not undoable", () => {
    expect(
      latestUndoableSale(history([{ ...base, can_undo_sale: false }])),
    ).toBeNull();
    expect(latestUndoableSale(null)).toBeNull();
  });
});

describe("undoTargetOperationId", () => {
  it("is the writing operation for an active row", () => {
    expect(undoTargetOperationId(base)).toBe("op-1");
  });
  it("is the voiding operation for a voided row (void-only corrections too)", () => {
    const voided = {
      ...base,
      voided_at: "2025-10-01T08:00:00+00:00",
      voided_operation_id: "op-void",
    };
    expect(undoTargetOperationId(voided)).toBe("op-void");
  });
});

describe("isBeforeLatestSnapshot", () => {
  it("compares against the latest Dec 30 on or before today", () => {
    const today = new Date(2026, 9, 2); // 2026-10-02 → latest snapshot 2025-12-30
    expect(isBeforeLatestSnapshot("2025-12-30", today)).toBe(true);
    expect(isBeforeLatestSnapshot("2025-12-31", today)).toBe(false);
    expect(isBeforeLatestSnapshot("2026-06-01", today)).toBe(false);
    expect(isBeforeLatestSnapshot("2026-06-01", new Date(2026, 11, 30))).toBe(
      true,
    );
  });
});

describe("newOperationId", () => {
  it("returns distinct v4 UUIDs", () => {
    const a = newOperationId();
    expect(a).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(newOperationId()).not.toBe(a);
  });
});

describe("newOperationId fallback", () => {
  afterEach(() => vi.unstubAllGlobals());
  it("builds a v4 UUID from getRandomValues when randomUUID is missing", () => {
    const real = globalThis.crypto;
    vi.stubGlobal("crypto", {
      getRandomValues: (a: Uint8Array) => real.getRandomValues(a),
    });
    expect(crypto.randomUUID).toBeUndefined();
    const id = newOperationId();
    expect(id).toMatch(
      /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    );
    expect(newOperationId()).not.toBe(id);
  });
});
