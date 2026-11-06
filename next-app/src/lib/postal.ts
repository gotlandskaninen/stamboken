// Client-side postnummer helpers. The server
// (utils/postal.normalize_postal_code) is the authority — these only make
// the input feel right and gate the obvious mistakes before a round trip.
const FIVE_DIGITS = /^(\d{3}) ?(\d{2})$/;

export function formatPostalCode(raw: string): string {
  const trimmed = raw.trim();
  const match = FIVE_DIGITS.exec(trimmed);
  return match ? `${match[1]} ${match[2]}` : trimmed;
}

export function isValidPostalCode(raw: string): boolean {
  const trimmed = raw.trim();
  return trimmed === "" || FIVE_DIGITS.test(trimmed);
}
