"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import ds from "@/styles/ds-admin.module.css";
import { STATUS_LABELS } from "./types";
import type { MembershipRow } from "./types";

const LIST_PATH = "/medlem/matrikel";
// Same compact metrics as the admin grids (Adminpanel.html:53-55).
const ROW_HEIGHT = 36;
const HEADER_HEIGHT = 40;

function EmptyMemberships() {
  return <div className={ds["ad-empty"]}>Inga medlemskap matchar.</div>;
}

const columns: GridColDef<MembershipRow>[] = [
  {
    field: "member_number",
    headerName: "Nr",
    width: 90,
    renderCell: (params) => (
      <Link
        href={`${LIST_PATH}/${params.row.id}`}
        className={`${ds["ad-cell-mono"]} ${ds["ad-cell-link"]}`}
        onClick={(e) => e.stopPropagation()}
      >
        {params.row.member_number ?? "—"}
      </Link>
    ),
  },
  {
    field: "membership_status",
    headerName: "Status",
    width: 120,
    valueGetter: (_value, row) =>
      STATUS_LABELS[row.membership_status] ?? row.membership_status,
  },
  {
    field: "main_member",
    headerName: "Huvudmedlem",
    flex: 1,
    minWidth: 160,
    valueGetter: (_value, row) =>
      [row.main_first_name, row.main_last_name].filter(Boolean).join(" ") ||
      "—",
  },
  {
    field: "contact",
    headerName: "Kontakt",
    flex: 1,
    minWidth: 180,
    cellClassName: ds["ad-cell-dim"],
    valueGetter: (_value, row) => row.main_email || row.main_phone || "—",
  },
  {
    field: "address",
    headerName: "Adress",
    flex: 1,
    minWidth: 200,
    // postal_address is derived server-side from postal_code + city.
    valueGetter: (_value, row) =>
      [row.address, row.postal_address].filter(Boolean).join(", ") || "—",
  },
  {
    field: "persons",
    headerName: "Personer",
    width: 100,
    valueGetter: (_value, row) =>
      row.persons.filter((p) => p.end_date === null).length,
  },
];

export function MembershipsGridClient({
  rows,
  total,
}: {
  rows: MembershipRow[];
  total: number;
}) {
  const router = useRouter();

  const handleRowClick = useCallback(
    (params: { row: MembershipRow }) => {
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
        sortModel={[]}
        disableColumnSorting
        onRowClick={handleRowClick}
        rowHeight={ROW_HEIGHT}
        columnHeaderHeight={HEADER_HEIGHT}
        hideFooter
        disableColumnFilter
        disableColumnMenu
        disableRowSelectionOnClick
        slots={{ noRowsOverlay: EmptyMemberships }}
        sx={{
          border: 0,
          "& .MuiDataGrid-row": { cursor: "pointer" },
        }}
      />
    </div>
  );
}
