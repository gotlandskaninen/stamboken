/** Shareable list URLs: a search param counts only as a positive integer — anything else falls back to the default. */
export function positiveInt(raw: string | string[] | undefined): number | null {
  const value = Array.isArray(raw) ? raw[0] : raw;
  if (value === undefined || value === "") return null;
  // Decimal digits only: Number() would otherwise widen the contract to
  // exponent ("1e3" -> 1000) and trailing-zero decimal ("1.0" -> 1) forms,
  // and to leading zeroes ("01"), none of which are positive integers as
  // written in the URL.
  if (!/^[1-9]\d*$/.test(value)) return null;
  const n = Number(value);
  // Past 2^53-1 Number() stops being exact: "9".repeat(400) is Infinity and
  // shorter huge values stringify in exponent form. page.tsx forwards the
  // value to the API before its clamp redirect, and Flask's int() answers 400
  // on either — so treat it as garbage and fall back to the default.
  return Number.isSafeInteger(n) ? n : null;
}
