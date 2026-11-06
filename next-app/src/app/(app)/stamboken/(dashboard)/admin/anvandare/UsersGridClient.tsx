"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DataGrid, GridColDef, GridSortModel } from "@mui/x-data-grid";
import { UserStatusBadges } from "../_components/UserStatusBadges";
import ds from "@/styles/ds-admin.module.css";

export type UserRow = {
  id: number;
  username: string | null;
  fullname: string | null;
  email: string;
  roleLabel: string;
  last_active: string;
  validated: boolean;
  v2_prod_access: boolean;
  is_active: boolean;
  google_linked: boolean;
};

const LIST_PATH = "/stamboken/admin/anvandare";
// 7px+7px cell padding + 20px line-box + 1px hairline (Adminpanel.html:55),
// rounded onto the 4px grid; header 9px+9px + 18px mono line + 1px (:53).
const ROW_HEIGHT = 36;
const HEADER_HEIGHT = 40;

function EmptyUsers() {
  return <div className={ds["ad-empty"]}>Inga användare matchar filtren.</div>;
}

const columns: GridColDef<UserRow>[] = [
  {
    field: "username",
    headerName: "Användarnamn",
    width: 130,
    renderCell: (params) => (
      <Link
        href={`${LIST_PATH}/${params.row.id}`}
        className={`${ds["ad-cell-mono"]} ${ds["ad-cell-link"]}`}
        onClick={(e) => e.stopPropagation()}
      >
        {params.row.username || "—"}
      </Link>
    ),
  },
  {
    field: "fullname",
    headerName: "Namn",
    flex: 1,
    minWidth: 160,
    valueGetter: (_value, row) => row.fullname || "—",
  },
  {
    field: "email",
    headerName: "E-post",
    flex: 1,
    minWidth: 200,
    cellClassName: ds["ad-cell-dim"],
  },
  { field: "roleLabel", headerName: "Roller", width: 280, sortable: false },
  {
    field: "status",
    headerName: "Status och åtkomst",
    width: 230,
    sortable: false,
    renderCell: (params) => (
      <UserStatusBadges
        validated={params.row.validated}
        v2ProdAccess={params.row.v2_prod_access}
        googleLinked={params.row.google_linked}
        isActive={params.row.is_active}
      />
    ),
  },
  {
    field: "last_active",
    headerName: "Senast aktiv",
    width: 150,
    cellClassName: `${ds["ad-cell-mono"]} ${ds["ad-cell-dim"]}`,
  },
];

export function UsersGridClient({
  rows,
  total,
  query,
  sortField,
  sortDir,
}: {
  rows: UserRow[];
  total: number;
  /** Current filter params, serialised by the RSC page (page/sort/dir included). */
  query: string;
  sortField: string;
  sortDir: "asc" | "desc";
}) {
  const router = useRouter();

  // Header sorting keeps the contract: it writes `sort`/`dir` to the URL
  // and the RSC page re-fetches. Backend sort keys: username | email |
  // fullname | last_active (data_access.py:3803-3810), dir=asc|desc
  // (blueprints/admin.py:212) — the four sortable columns map 1:1.
  const handleSortModelChange = useCallback(
    (model: GridSortModel) => {
      const next = new URLSearchParams(query);
      const entry = model[0];
      if (entry?.sort) {
        next.set("sort", entry.field);
        next.set("dir", entry.sort);
      } else {
        next.delete("sort");
        next.delete("dir");
      }
      next.delete("page");
      router.push(`${LIST_PATH}?${next.toString()}`);
    },
    [query, router],
  );

  const handleRowClick = useCallback(
    (params: { row: UserRow }) => {
      router.push(`${LIST_PATH}/${params.row.id}`);
    },
    [router],
  );

  return (
    <div
      style={{
        height: HEADER_HEIGHT + Math.max(rows.length, 3) * ROW_HEIGHT,
      }}
    >
      <DataGrid
        rows={rows}
        columns={columns}
        rowCount={total}
        paginationMode="server"
        sortingMode="server"
        filterMode="server"
        sortModel={[{ field: sortField, sort: sortDir }]}
        onSortModelChange={handleSortModelChange}
        onRowClick={handleRowClick}
        rowHeight={ROW_HEIGHT}
        columnHeaderHeight={HEADER_HEIGHT}
        hideFooter
        disableColumnFilter
        disableColumnMenu
        disableRowSelectionOnClick
        slots={{ noRowsOverlay: EmptyUsers }}
        sx={{
          border: 0,
          "& .MuiDataGrid-row": { cursor: "pointer" },
        }}
      />
    </div>
  );
}
