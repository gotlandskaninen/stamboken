import Link from "next/link";
import { redirect } from "next/navigation";
import { MenuItem, TextField } from "@mui/material";
import { fetchApi } from "@/lib/api";
import { requireHerdAdmin } from "../_lib/requireAdmin";
import ds from "@/styles/ds-admin.module.css";
import { HerdListGrid, type HerdListRow } from "./HerdListGrid";

export const dynamic = "force-dynamic";

interface HerdListResponse {
  herds: HerdListRow[];
  total: number;
  page: number;
  page_size: number;
}

const PAGE_SIZE = 50;

export default async function HerdListPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const user = await requireHerdAdmin();
  const sp = await searchParams;
  // Positivt heltal — bråktal/NaN/negativt blir sida 1; över-taket
  // omdirigeras till sista sidan nedan.
  const page = Math.max(1, Math.trunc(Number(sp.page ?? "1")) || 1);

  let herds: HerdListRow[];
  let total: number;

  if (user.is_admin) {
    const qs = new URLSearchParams({
      page: String(page),
      page_size: String(PAGE_SIZE),
    });
    if (sp.genebank_id) qs.set("genebank_id", sp.genebank_id);
    if (sp.active) qs.set("active", sp.active);
    if (sp.has_owner) qs.set("has_owner", sp.has_owner);
    if (sp.q) qs.set("q", sp.q);
    const body = await fetchApi<HerdListResponse>(
      `/manage/herd?${qs.toString()}`,
      { forceProd: true }, // Admin reads force prod too.
    );
    herds = body.herds;
    total = body.total;
  } else {
    // Manager: scoped rows via the gb detail endpoint
    // (GET /api/manage/herd is admin-only in Phase 17; managers 403).
    const parts = await Promise.all(
      (user.is_manager ?? []).map(async (gbId) => {
        const gb = await fetchApi<{
          name: string;
          herds: {
            id: number;
            herd: string;
            herd_name: string | null;
            is_active: boolean | null;
          }[];
        }>(`/genebank/${gbId}`, { forceProd: true });
        return (gb.herds ?? []).map((h) => ({
          id: h.id,
          herd: h.herd,
          herd_name: h.herd_name,
          genebank_name: gb.name,
          owner_usernames: [], // gb herd rows carry no owner join
          is_active: h.is_active ?? false,
        }));
      }),
    );
    herds = parts.flat();
    // Same free-text filter as the admin API applies server-side.
    if (sp.q) {
      const needle = sp.q.trim().toLowerCase();
      herds = herds.filter(
        (h) =>
          h.herd.toLowerCase().includes(needle) ||
          (h.herd_name ?? "").toLowerCase().includes(needle),
      );
    }
    total = herds.length;
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageHref = (p: number) => {
    const qs = new URLSearchParams();
    for (const k of ["genebank_id", "active", "has_owner", "q"]) {
      if (sp[k]) qs.set(k, sp[k] as string);
    }
    qs.set("page", String(p));
    return `/stamboken/admin/besattningar?${qs.toString()}`;
  };
  // Utanför sista sidan → sista sidan. Utan detta blir t.ex. ?page=2 med
  // ≤50 träffar en tom lista UTAN sidlänkar att ta sig tillbaka med
  // (fotens länkar renderas bara när totalPages > 1).
  if (page > totalPages) redirect(pageHref(totalPages));
  if (!user.is_admin) {
    // MIT-DataGrid kastar fel 83 för pageSize > 100 (GK har 1000+
    // besättningar), så managern får samma URL-drivna sidnumrering som
    // admin i stället för allt-på-en-sida.
    herds = herds.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  }

  return (
    <>
      <div className={ds["ad-page-head"]}>
        <h2 className={ds["ad-page-title"]}>
          Besättningar <span className={ds["ad-count"]}>{total}</span>
        </h2>
        <Link
          href="/stamboken/admin/besattningar/ny"
          className="sb-btn sb-btn-sm"
        >
          <span aria-hidden="true">+</span> Ny besättning
        </Link>
      </div>
      <div className={`sb-card ${ds["ad-grid"]}`}>
        {user.is_admin && (
          <form method="get" className={ds["ad-grid-toolbar"]}>
            <input
              type="text"
              name="q"
              defaultValue={sp.q ?? ""}
              placeholder="Sök besättningsnummer eller namn…"
              aria-label="Sök besättningsnummer eller namn"
              className={`sb-input ${ds["ad-search"]}`}
            />
            <TextField
              select
              name="genebank_id"
              label="Genbank"
              defaultValue={sp.genebank_id ?? ""}
              size="small"
              sx={{ minWidth: 150 }}
            >
              <MenuItem value="">Alla</MenuItem>
              <MenuItem value="1">Gotlandskanin</MenuItem>
              <MenuItem value="2">Mellerudskanin</MenuItem>
            </TextField>
            <TextField
              select
              name="active"
              label="Status"
              defaultValue={sp.active ?? ""}
              size="small"
              sx={{ minWidth: 110 }}
            >
              <MenuItem value="">Alla</MenuItem>
              <MenuItem value="true">Aktiva</MenuItem>
              <MenuItem value="false">Inaktiva</MenuItem>
            </TextField>
            <TextField
              select
              name="has_owner"
              label="Ägare"
              defaultValue={sp.has_owner ?? ""}
              size="small"
              sx={{ minWidth: 130 }}
            >
              <MenuItem value="">Alla</MenuItem>
              <MenuItem value="true">Har ägare</MenuItem>
              <MenuItem value="false">Saknar ägare</MenuItem>
            </TextField>
            <button type="submit" className="sb-btn sb-btn-secondary sb-btn-sm">
              Filtrera
            </button>
          </form>
        )}
        <HerdListGrid rows={herds} pageSize={PAGE_SIZE} rowCount={total} />
        <div className={ds["ad-grid-foot"]}>
          <span className="sb-meta">
            {total} {total === 1 ? "besättning" : "besättningar"}
          </span>
          <span className={ds["ad-grid-spacer"]} />
          {totalPages > 1 && (
            <>
              <span className="sb-meta">
                Sida {page} av {totalPages}
              </span>
              {page > 1 && (
                <Link
                  href={pageHref(page - 1)}
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                >
                  Föregående
                </Link>
              )}
              {page < totalPages && (
                <Link
                  href={pageHref(page + 1)}
                  className="sb-btn sb-btn-secondary sb-btn-sm"
                >
                  Nästa
                </Link>
              )}
            </>
          )}
        </div>
      </div>
    </>
  );
}
