"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import ds from "@/styles/ds-admin.module.css";

export type ApplicationRow = {
  id: number;
  first_name: string;
  last_name: string;
  email: string;
  created_at: string;
};

const LIST_PATH = "/medlem/ansokningar";
// Same compact metrics as the admin grids (Adminpanel.html:53-55).
const ROW_HEIGHT = 36;
const HEADER_HEIGHT = 40;

function EmptyApplications() {
  return <div className={ds["ad-empty"]}>Inga ansökningar att granska.</div>;
}

const fullName = (row: ApplicationRow) =>
  [row.first_name, row.last_name].filter(Boolean).join(" ") || "—";

const columns: GridColDef<ApplicationRow>[] = [
  {
    field: "name",
    headerName: "Namn",
    flex: 1,
    minWidth: 180,
    valueGetter: (_value, row) => fullName(row),
    // A real anchor, not just onRowClick: keyboard Enter, middle-click and
    // "open in new tab" all have to reach the detail page (same as the
    // matrikel grid's Nr column).
    renderCell: (params) => (
      <Link
        href={`${LIST_PATH}/${params.row.id}`}
        className={ds["ad-cell-link"]}
        onClick={(e) => e.stopPropagation()}
      >
        {fullName(params.row)}
      </Link>
    ),
  },
  {
    field: "email",
    headerName: "E-post",
    flex: 1,
    minWidth: 200,
    cellClassName: ds["ad-cell-dim"],
  },
  {
    field: "created_at",
    headerName: "Inskickad",
    width: 180,
    valueGetter: (_value, row) =>
      new Date(row.created_at).toLocaleString("sv-SE"),
  },
];

export function ApplicationsGridClient({ rows }: { rows: ApplicationRow[] }) {
  const router = useRouter();

  const handleRowClick = useCallback(
    (params: { row: ApplicationRow }) => {
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
      {/* The pending queue is short — everything is client-side and the
          footer stays hidden (no pagination). */}
      <DataGrid
        rows={rows}
        columns={columns}
        onRowClick={handleRowClick}
        rowHeight={ROW_HEIGHT}
        columnHeaderHeight={HEADER_HEIGHT}
        hideFooter
        disableColumnSorting
        disableColumnFilter
        disableColumnMenu
        disableRowSelectionOnClick
        slots={{ noRowsOverlay: EmptyApplications }}
        sx={{
          border: 0,
          "& .MuiDataGrid-row": { cursor: "pointer" },
        }}
      />
    </div>
  );
}
