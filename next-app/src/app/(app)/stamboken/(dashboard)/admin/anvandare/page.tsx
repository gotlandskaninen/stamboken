import Link from "next/link";
import { FormControl, MenuItem, Select } from "@mui/material";
import { fetchApi } from "@/lib/api";
import { requireAdmin } from "../_lib/requireAdmin";
import { roleSummaryLabel } from "../_lib/roleSummaryLabel";
import type { AdminUserListItem } from "../_lib/types";
import { UsersGridClient, type UserRow } from "./UsersGridClient";
import ds from "@/styles/ds-admin.module.css";

export const dynamic = "force-dynamic";

// Envelope from GET /api/v2/admin/users — verified at impl:
// data_access.list_admin_users returns { users, total, page, per_page }.
type UserListResponse = {
  users: AdminUserListItem[];
  total: number;
  page: number;
  per_page: number;
};

// Query params (+ `active`).
const FILTER_KEYS = [
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

const PER_PAGE_OPTIONS = [25, 50, 100, 200];
const DEFAULT_PER_PAGE = 50;

function formatLastActive(value: string | null): string {
  if (!value) return "aldrig";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleString("sv-SE", { timeZone: "Europe/Stockholm" });
}

export default async function AdminUsersPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  await requireAdmin(); // Page-level gate, layout renders concurrently
  const sp = await searchParams;
  const qs = new URLSearchParams();
  for (const key of FILTER_KEYS) {
    const v = sp[key];
    if (v) qs.set(key, v);
  }
  // Sidstorlek: API-default är 25 (tak 200); besättningslistan visar 50, så
  // samma här. Ogiltiga/okända värden faller tillbaka till 50.
  const requestedPerPage = Number(sp.per_page);
  const perPage = PER_PAGE_OPTIONS.includes(requestedPerPage)
    ? requestedPerPage
    : DEFAULT_PER_PAGE;
  qs.set("per_page", String(perPage));
  const body = await fetchApi<UserListResponse>(
    `/v2/admin/users?${qs.toString()}`,
    { forceProd: true },
  );
  const page = body.page || 1;
  const lastPage = Math.max(1, Math.ceil(body.total / perPage));
  const pageHref = (p: number) => {
    const next = new URLSearchParams(qs);
    next.set("page", String(p));
    return `/stamboken/admin/anvandare?${next.toString()}`;
  };
  const perPageHref = (n: number) => {
    const next = new URLSearchParams(qs);
    next.set("per_page", String(n));
    next.delete("page"); // ny sidstorlek → börja om från sida 1
    return `/stamboken/admin/anvandare?${next.toString()}`;
  };
  const sortField = sp.sort ?? "last_active";
  const sortDir = sp.dir === "asc" ? "asc" : "desc";
  const rows: UserRow[] = body.users.map((u) => ({
    id: u.id,
    username: u.username,
    fullname: u.fullname,
    email: u.email,
    roleLabel: roleSummaryLabel(u.role_summary),
    last_active: formatLastActive(u.last_active),
    validated: u.validated,
    v2_prod_access: u.v2_prod_access,
    is_active: u.is_active,
    google_linked: u.google_linked,
  }));

  return (
    <>
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>
          Användare <span className={ds["ad-count"]}>{body.total}</span>
        </h2>
      </div>

      <section className={`sb-card ${ds["ad-grid"]}`}>
        {/* Plain GET form → URL params → server-rendered result. */}
        <form
          method="get"
          action="/stamboken/admin/anvandare"
          className={ds["ad-grid-toolbar"]}
        >
          <input
            type="text"
            name="search"
            defaultValue={sp.search ?? ""}
            className={`sb-input ${ds["ad-search"]}`}
            placeholder="Sök användarnamn, e-post eller namn…"
            aria-label="Sök efter användarnamn, e-postadress eller namn"
          />
          <FormControl size="small" className={ds["ad-filter"]}>
            <span className={ds["ad-filter-label"]} id="ad-f-role">
              Roll
            </span>
            <Select
              name="role"
              defaultValue={sp.role ?? ""}
              aria-labelledby="ad-f-role"
              sx={{ width: 200 }}
            >
              <MenuItem value="">Alla</MenuItem>
              <MenuItem value="admin">Administratör</MenuItem>
              <MenuItem value="matrikel_admin">Matrikeladministratör</MenuItem>
              <MenuItem value="manager">Genbanksansvarig</MenuItem>
              <MenuItem value="viewer">Granskare</MenuItem>
              <MenuItem value="owner">Besättningsägare</MenuItem>
              <MenuItem value="none">Ingen roll</MenuItem>
            </Select>
          </FormControl>
          <FormControl size="small" className={ds["ad-filter"]}>
            <span className={ds["ad-filter-label"]} id="ad-f-active">
              Konto
            </span>
            <Select
              name="active"
              defaultValue={sp.active ?? ""}
              aria-labelledby="ad-f-active"
              sx={{ width: 110 }}
            >
              <MenuItem value="">Alla</MenuItem>
              <MenuItem value="true">Aktiv</MenuItem>
              <MenuItem value="false">Inaktiv</MenuItem>
            </Select>
          </FormControl>
          <FormControl size="small" className={ds["ad-filter"]}>
            <span className={ds["ad-filter-label"]} id="ad-f-prod">
              Riktiga stamboken
            </span>
            <Select
              name="v2_prod_access"
              defaultValue={sp.v2_prod_access ?? ""}
              aria-labelledby="ad-f-prod"
              sx={{ width: 90 }}
            >
              <MenuItem value="">Alla</MenuItem>
              <MenuItem value="true">Ja</MenuItem>
              <MenuItem value="false">Nej</MenuItem>
            </Select>
          </FormControl>
          <FormControl size="small" className={ds["ad-filter"]}>
            <span className={ds["ad-filter-label"]} id="ad-f-validated">
              Webbkurs
            </span>
            <Select
              name="validated"
              defaultValue={sp.validated ?? ""}
              aria-labelledby="ad-f-validated"
              sx={{ width: 90 }}
            >
              <MenuItem value="">Alla</MenuItem>
              <MenuItem value="true">Ja</MenuItem>
              <MenuItem value="false">Nej</MenuItem>
            </Select>
          </FormControl>
          {/* sort/dir/per_page have no control — carry them so a filter
              submit does not silently reset the sort order (page DOES
              reset to 1, which is intended). */}
          {sp.sort && <input type="hidden" name="sort" value={sp.sort} />}
          {sp.dir && <input type="hidden" name="dir" value={sp.dir} />}
          {sp.per_page && (
            <input type="hidden" name="per_page" value={sp.per_page} />
          )}
          <button type="submit" className="sb-btn sb-btn-sm">
            Filtrera
          </button>
        </form>

        <UsersGridClient
          rows={rows}
          total={body.total}
          query={qs.toString()}
          sortField={sortField}
          sortDir={sortDir}
        />

        <div className={ds["ad-grid-foot"]}>
          <span className="sb-meta">{body.total} användare</span>
          <nav className={ds["ad-per-page"]} aria-label="Rader per sida">
            <span className="sb-meta">Per sida:</span>
            {PER_PAGE_OPTIONS.map((n) =>
              n === perPage ? (
                <span key={n} className="sb-meta" aria-current="true">
                  <strong>{n}</strong>
                </span>
              ) : (
                <Link key={n} href={perPageHref(n)} className="sb-meta">
                  {n}
                </Link>
              ),
            )}
          </nav>
          <span className={ds["ad-grid-spacer"]} />
          <span className="sb-meta">
            Sida {page} av {lastPage}
          </span>
          {page > 1 ? (
            <Link
              href={pageHref(page - 1)}
              className="sb-btn sb-btn-secondary sb-btn-sm"
            >
              Föregående
            </Link>
          ) : (
            <span
              className={`sb-btn sb-btn-secondary sb-btn-sm ${ds["ad-btn-disabled"]}`}
              aria-disabled="true"
            >
              Föregående
            </span>
          )}
          {page < lastPage ? (
            <Link
              href={pageHref(page + 1)}
              className="sb-btn sb-btn-secondary sb-btn-sm"
            >
              Nästa
            </Link>
          ) : (
            <span
              className={`sb-btn sb-btn-secondary sb-btn-sm ${ds["ad-btn-disabled"]}`}
              aria-disabled="true"
            >
              Nästa
            </span>
          )}
        </div>
      </section>
    </>
  );
}
