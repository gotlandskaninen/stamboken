import { assertNever } from "./assertNever";

// Source of truth for the values and the legal transitions:
// app/utils/membership_lifecycle.py (StrEnum `Status`; the DB has a CHECK on them).
export const MEMBERSHIP_STATUSES = [
  "active",
  "inactive",
  "pending",
  "friexemplar",
] as const;

export type MembershipStatus = (typeof MEMBERSHIP_STATUSES)[number];

type Tone = "skog" | "default" | "warning" | "himmel";

export const MEMBERSHIP_STATUS: Record<
  MembershipStatus,
  { label: string; tone: Tone }
> = {
  active: { label: "Aktiv", tone: "skog" },
  inactive: { label: "Inaktiv", tone: "default" },
  pending: { label: "Väntar", tone: "warning" },
  friexemplar: { label: "Friexemplar", tone: "himmel" },
};

/** What "Ny medlem" may create: everything except an already-inactive one. */
export const CREATABLE_STATUSES = MEMBERSHIP_STATUSES.filter(
  (s) => s !== "inactive",
);

export const isMembershipStatus = (v: unknown): v is MembershipStatus =>
  (MEMBERSHIP_STATUSES as readonly unknown[]).includes(v);

/** Label for a value from the API; an unknown value renders as itself. */
export const statusLabel = (s: string): string =>
  isMembershipStatus(s) ? MEMBERSHIP_STATUS[s].label : s;

/**
 * Badge label + class. `warningClass` is the `badgeWarning` class of the CSS
 * module the caller imports (the modifier is module-local, not global).
 */
export function statusBadge(
  s: string,
  warningClass: string,
): { label: string; className: string } {
  if (!isMembershipStatus(s)) return { label: s, className: "sb-badge" };
  const { label, tone } = MEMBERSHIP_STATUS[s];
  switch (tone) {
    case "skog":
      return { label, className: "sb-badge sb-badge-skog" };
    case "himmel":
      return { label, className: "sb-badge sb-badge-himmel" };
    case "warning":
      return { label, className: `sb-badge ${warningClass}` };
    case "default":
      return { label, className: "sb-badge" };
    default:
      return assertNever(tone);
  }
}
