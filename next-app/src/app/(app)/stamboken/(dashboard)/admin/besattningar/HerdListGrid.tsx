"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { DataGrid, type GridColDef } from "@mui/x-data-grid";
import ds from "@/styles/ds-admin.module.css";

// Flyttad ordagrant från besattningar/page.tsx:17-24 — gridet äger radformen,
// sidan behåller HerdListResponse.
export interface HerdListRow {
  id: number;
  herd: string;
  herd_name: string | null;
  genebank_name: string;
  owner_usernames: string[];
  is_active: boolean;
}

// sortable: false överallt. Server-sidnumreringen (PAGE_SIZE 50) gör att
// klientsortering bara skulle sortera de 50 synliga raderna.
const columns: GridColDef<HerdListRow>[] = [
  {
    field: "herd",
    headerName: "Besättning",
    width: 130,
    sortable: false,
    renderCell: ({ row }) => (
      <Link
        href={`/stamboken/admin/besattningar/${row.herd}`}
        className={`${ds["ad-cell-mono"]} ${ds["ad-cell-link"]}`}
        onClick={(e) => e.stopPropagation()}
      >
        {row.herd}
      </Link>
    ),
  },
  {
    field: "herd_name",
    headerName: "Namn",
    flex: 1,
    minWidth: 160,
    sortable: false,
    valueGetter: (value: string | null) => value ?? "—",
  },
  {
    field: "genebank_name",
    headerName: "Genbank",
    width: 150,
    sortable: false,
    cellClassName: ds["ad-cell-dim"],
  },
  {
    field: "owner_usernames",
    headerName: "Ägare",
    flex: 1,
    minWidth: 160,
    sortable: false,
    cellClassName: `${ds["ad-cell-mono"]} ${ds["ad-cell-dim"]}`,
    valueGetter: (value: string[]) =>
      value.length > 0 ? value.join(", ") : "—",
  },
  {
    field: "is_active",
    headerName: "Status",
    width: 110,
    sortable: false,
    renderCell: ({ row }) =>
      row.is_active ? (
        <span className="sb-badge sb-badge-mossa">Aktiv</span>
      ) : (
        <span className="sb-badge">Inaktiv</span>
      ),
  },
];

/**
 * Alltid paginationMode="server": sidan (page.tsx) har redan skurit ut
 * PAGE_SIZE-sidan — admin via API:ets page-param, manager via slice() på
 * den ihopsamlade mängden. MIT-DataGrid tillåter inte pageSize > 100
 * (fel 83), så managerns tidigare allt-på-en-sida-läge var omöjligt mot
 * riktig data (GK har 1000+ besättningar).
 * Fotraden är alltid dold — sidnumreringen är URL-driven och renderas av
 * Server-komponenten som riktiga <Link>:ar (.ad-grid-foot).
 */
export function HerdListGrid({
  rows,
  pageSize,
  rowCount,
}: {
  rows: HerdListRow[];
  pageSize: number;
  rowCount: number;
}) {
  const router = useRouter();
  return (
    <div className={ds["ad-grid-body"]}>
      <DataGrid
        rows={rows}
        columns={columns}
        rowCount={rowCount}
        paginationMode="server"
        pageSizeOptions={[pageSize]}
        initialState={{
          pagination: { paginationModel: { page: 0, pageSize } },
        }}
        hideFooter
        disableColumnMenu
        disableRowSelectionOnClick
        onRowClick={(params) =>
          router.push(`/stamboken/admin/besattningar/${params.row.herd}`)
        }
        localeText={{ noRowsLabel: "Inga besättningar matchar filtret." }}
        // border: 0 — temats MuiDataGrid-override ritar 1px --sb-line +
        // radie, men här sitter gridet inuti ett .sb-card som redan har båda.
        sx={{ border: 0, "& .MuiDataGrid-row": { cursor: "pointer" } }}
      />
    </div>
  );
}
