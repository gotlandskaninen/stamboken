import Link from "next/link";
import { redirect } from "next/navigation";
import { FormControl, MenuItem, Select } from "@mui/material";
import { fetchApi } from "@/lib/api";
import { getUser } from "@/lib/auth";
import { Masthead } from "@/components/shell/Masthead";
import ds from "@/styles/ds-admin.module.css";
import styles from "../medlem.module.css";
import { MembershipsGridClient } from "./MembershipsGridClient";
import { positiveInt } from "./query";
import { NewMembershipButton } from "./NewMembershipDialog";
import { ExportButtons } from "./ExportButtons";
import type { MembershipRow } from "./types";
import { MEMBERS_PAGE_SIZE } from "./types";

export const dynamic = "force-dynamic";

type ListResponse = {
  items: MembershipRow[];
  total: number;
  page: number;
  per_page: number;
};
const LIST_PATH = "/medlem/matrikel";

export default async function MembershipsListPage({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | undefined>>;
}) {
  const sp = await searchParams;
  // Only positive integers reach the API — `?page=1.5` would otherwise be
  // forwarded and answered 400.
  const perPage = Math.min(100, positiveInt(sp.per_page) ?? MEMBERS_PAGE_SIZE);
  const requestedPage = positiveInt(sp.page) ?? 1;
  const qs = new URLSearchParams();
  if (sp.search) qs.set("search", sp.search);
  if (sp.status) qs.set("status", sp.status);
  qs.set("per_page", String(perPage));
  qs.set("page", String(requestedPage));
  const body = await fetchApi<ListResponse>(`/v2/members?${qs.toString()}`);
  const lastPage = Math.max(1, Math.ceil(body.total / perPage));
  if (requestedPage > lastPage) {
    // Clamp out-of-range pages — a shareable URL never renders an
    // empty grid.
    qs.set("page", String(lastPage));
    redirect(`${LIST_PATH}?${qs.toString()}`);
  }
  const user = await getUser();
  const canEdit = Boolean(user?.is_admin) || Boolean(user?.is_matrikel_admin);
  const pageHref = (p: number) => {
    const next = new URLSearchParams(qs);
    next.set("page", String(p));
    return `${LIST_PATH}?${next.toString()}`;
  };

  return (
    <>
      <Masthead
        eyebrow="Matrikel"
        title="Medlemsmatrikel"
        meta={`${body.total.toLocaleString("sv-SE")} medlemskap`}
        actions={canEdit ? <NewMembershipButton /> : undefined}
      />
      <div className={styles.container}>
        <section className={`sb-card ${ds["ad-grid"]}`}>
          {/* Plain GET form → URL params → server-rendered result. */}
          <form
            method="get"
            action={LIST_PATH}
            className={ds["ad-grid-toolbar"]}
          >
            <input
              type="text"
              name="search"
              defaultValue={sp.search ?? ""}
              className={`sb-input ${ds["ad-search"]}`}
              placeholder="Sök namn, e-post eller medlemsnr"
              aria-label="Sök namn, e-post eller medlemsnummer"
            />
            <FormControl size="small" className={ds["ad-filter"]}>
              <span className={ds["ad-filter-label"]} id="mat-f-status">
                Status
              </span>
              <Select
                name="status"
                defaultValue={sp.status ?? ""}
                aria-labelledby="mat-f-status"
                className={styles.statusSelect}
              >
                <MenuItem value="">Alla</MenuItem>
                <MenuItem value="active">Aktiv</MenuItem>
                <MenuItem value="inactive">Inaktiv</MenuItem>
                <MenuItem value="pending">Väntar</MenuItem>
                <MenuItem value="friexemplar">Friexemplar</MenuItem>
              </Select>
            </FormControl>
            <input type="hidden" name="per_page" value={perPage} />
            <button type="submit" className="sb-btn sb-btn-sm">
              Filtrera
            </button>
            {canEdit && <ExportButtons />}
          </form>
          <MembershipsGridClient rows={body.items} total={body.total} />
          <div className={ds["ad-grid-foot"]}>
            <span className="sb-meta">{body.total} medlemskap</span>
            <span className={ds["ad-grid-spacer"]} />
            <span className="sb-meta">
              Sida {body.page} av {lastPage}
            </span>
            {body.page > 1 ? (
              <Link
                href={pageHref(body.page - 1)}
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
            {body.page < lastPage ? (
              <Link
                href={pageHref(body.page + 1)}
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
      </div>
    </>
  );
}
