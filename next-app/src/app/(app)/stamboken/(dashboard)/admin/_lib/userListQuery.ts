// The account list's search, filters, sort and page as a query string. The
// list hands it to each account and the account's back link returns it, so
// the list keeps them (#249). Only these keys travel.
const USER_LIST_KEYS = [
  "search",
  "role",
  "validated",
  "active",
  "v2_prod_access",
  "sort",
  "dir",
  "page",
  "per_page",
] as const;

export function userListQuery(
  sp: Record<string, string | string[] | undefined>,
): string {
  const qs = new URLSearchParams();
  for (const key of USER_LIST_KEYS) {
    const v = sp[key];
    const first = Array.isArray(v) ? v[0] : v; // a repeated key: the first
    if (first) qs.set(key, first);
  }
  return qs.toString();
}
