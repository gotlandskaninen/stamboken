import { addDays, format, isValid, parseISO, startOfDay } from "date-fns";

/** Herd codes meaning "sold outside the genebank" (one per genebank). */
export const OUTSIDE_GENEBANK_HERDS = ["GX1", "MX1"] as const;

export const MIN_SALE_AGE_DAYS = 43;

/** Herd as listed by GET /api/v2/genebank/<id>/herds. */
export interface GenebankHerd {
  herd: string;
  herd_name: string | null;
  is_active: boolean;
}

export function isOutsideGenebankHerd(code: string): boolean {
  return (OUTSIDE_GENEBANK_HERDS as readonly string[]).includes(code);
}

interface TrackingRow {
  date: string | null;
}

/**
 * Earliest allowed sale date (mirrors legacy and the API): birth + 43 days
 * when the latest herd-tracking row is the birth row (or there is none),
 * otherwise the day after the latest herd-tracking date.
 */
export function minSaleDate(
  birthDate: string | null | undefined,
  herdTracking: TrackingRow[] | null | undefined,
): Date | null {
  const latest = (herdTracking ?? [])
    .map((row) => row.date)
    .filter((d): d is string => !!d)
    .sort()
    .at(-1);
  if (latest && latest !== birthDate) return addDays(parseISO(latest), 1);
  if (birthDate) return addDays(parseISO(birthDate), MIN_SALE_AGE_DAYS);
  return null;
}

/**
 * Today's calendar date in Stockholm (the API validates against it), as a Date at
 * local midnight so it compares with date-picker values. The browser's own
 * timezone must not decide what "today" is.
 */
export function stockholmToday(now: Date = new Date()): Date {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Europe/Stockholm",
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).formatToParts(now);
  const part = (type: string) =>
    Number(parts.find((p) => p.type === type)?.value);
  return new Date(part("year"), part("month") - 1, part("day"));
}

export type SaleDateProblem = "invalid" | "future" | "tooEarly";

export function validateSaleDate(
  date: Date | null,
  min: Date | null,
  today: Date = stockholmToday(),
): SaleDateProblem | null {
  if (!date || !isValid(date)) return "invalid";
  if (startOfDay(date) > startOfDay(today)) return "future";
  if (min && startOfDay(date) < startOfDay(min)) return "tooEarly";
  return null;
}

export const toIsoDate = (date: Date): string => format(date, "yyyy-MM-dd");
