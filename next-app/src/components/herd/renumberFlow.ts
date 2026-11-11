import { assertNever } from "@/lib/assertNever";

/** One state for the whole renumber flow, so a failed call cannot leave the dialog stuck. */
export type RenumberFlow<D> =
  | { phase: "closed" }
  | { phase: "conflict"; data: D; error?: string }
  | { phase: "renumbering"; data: D };

/** The dialog props that depend on the phase. */
export function renumberView(flow: RenumberFlow<unknown>): {
  isRenumbering: boolean;
  error: string | null;
} {
  switch (flow.phase) {
    case "closed":
      return { isRenumbering: false, error: null };
    case "conflict":
      return { isRenumbering: false, error: flow.error ?? null };
    case "renumbering":
      return { isRenumbering: true, error: null };
    default:
      return assertNever(flow);
  }
}
