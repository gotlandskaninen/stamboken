import React, { useMemo, useState } from "react";
import Link from "next/link";
import styled from "@emotion/styled";

import {
  Box,
  Chip as MuiChip,
  Skeleton,
  Alert,
  Typography,
} from "@mui/material";
import { DataGrid, GridColDef, GridSortModel } from "@mui/x-data-grid";
import CheckIcon from "@mui/icons-material/Check";

import { decimal, percent } from "@/lib/genetics";
import HelpTooltip from "./HelpTooltip";
import GeneticsInfoPanel from "./GeneticsInfoPanel";
import GeneticsError from "./GeneticsError";
import { readableChip } from "./readableChip";
import { translateReasons } from "@/utils/translateReasons";
import { readModeCookieClient } from "@/lib/mode";
import { useMode } from "@/lib/mode-context";
import {
  PRIORITY_LABEL,
  PRIORITY_ORDER,
  byHerd,
  downloadExport,
  exportRefusal,
  prioritiesCsvUrl,
  sexLabel,
  useWorkList,
} from "./workList";

const RARE_GENES =
  "Hur stor andel av kaninerna i beräkningen som är mer släkt med resten än den här kaninen. 100 betyder minst släkt, alltså mest ovanliga gener.";
const UNIQUE_GENES =
  "Sannolikheten att kaninen bär genvarianter från founderdjuren som ingen annan kanin i beräkningen bär, enligt en simulering av hur generna ärvs genom stamtavlan.";

const FilterChip = styled(MuiChip)`
  margin-right: ${(props) => props.theme.spacing(1)};
  margin-bottom: ${(props) => props.theme.spacing(2)};
`;

// Off: outlined in ink, full contrast; on: the level's colour and a check mark.
const chipOff = {
  color: "var(--sb-ink-2)",
  borderColor: "var(--sb-line-strong)",
};

const priorityConfig: Record<
  string,
  { label: string; chipColor: "error" | "warning" | "default" }
> = {
  critical: { label: PRIORITY_LABEL.critical, chipColor: "error" },
  important: { label: PRIORITY_LABEL.important, chipColor: "warning" },
  normal: { label: PRIORITY_LABEL.normal, chipColor: "default" },
};

const linkCell = (href: string, text: string) => (
  <Link href={href} className="sb-link">
    {text}
  </Link>
);

interface PrioritiesTabProps {
  genebankId: number;
}

const PrioritiesTab = ({ genebankId }: PrioritiesTabProps) => {
  const mode = useMode(); // the view's own mode, as the server rendered it
  // Every read of the list is logged on the server; the tab is keyed per genebank.
  const {
    data: priorities,
    isLoading,
    error,
    refetch,
  } = useWorkList(genebankId, mode);

  const [filters, setFilters] = useState({
    critical: true,
    important: true,
    normal: true,
  });

  const toggleFilter = (level: keyof typeof filters) => {
    setFilters((prev) => ({ ...prev, [level]: !prev[level] }));
  };

  // Per besättning: the rows in herd order within each level; the grid's own sort is cleared.
  const [perHerd, setPerHerd] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [sortModel, setSortModel] = useState<GridSortModel>([
    { field: "priority", sort: "asc" },
  ]);

  const filteredRows = useMemo(() => {
    if (!priorities) return [];
    const shown = priorities.filter(
      (p) => filters[p.priority as keyof typeof filters],
    );
    return (perHerd ? byHerd(shown) : shown).map((p, index) => ({
      ...p,
      id: p.individual_id || index,
    }));
  }, [priorities, filters, perHerd]);

  const columns: GridColDef[] = [
    {
      field: "individual_id",
      headerName: "Individnummer",
      width: 125,
      renderCell: ({ value }) =>
        linkCell(`/stamboken/individ/${encodeURIComponent(value)}`, value),
    },
    {
      field: "name",
      headerName: "Namn",
      width: 110,
      valueFormatter: (value?: string | null) => value || "–",
    },
    {
      field: "herd",
      headerName: "Besättning",
      width: 100,
      renderCell: ({ value }) =>
        value
          ? linkCell(
              `/stamboken/min-besattning?herd=${encodeURIComponent(value)}`,
              value,
            )
          : "–",
    },
    {
      field: "sex",
      headerName: "Kön",
      width: 70,
      // undefined: the database no longer has the number; null: unknown sex.
      valueFormatter: (value?: string | null) =>
        value === undefined ? "–" : sexLabel(value),
    },
    {
      field: "birth_date",
      headerName: "Född",
      width: 100,
      valueFormatter: (value?: string | null) => value || "–",
    },
    {
      field: "priority",
      headerName: "Avelsprioritet",
      width: 165,
      renderCell: (params) => {
        const config = priorityConfig[params.value] || priorityConfig.normal;
        return (
          <MuiChip
            label={config.label}
            color={config.chipColor}
            size="small"
            sx={readableChip}
          />
        );
      },
      sortComparator: (v1, v2) =>
        (PRIORITY_ORDER[v1 as keyof typeof PRIORITY_ORDER] ?? 3) -
        (PRIORITY_ORDER[v2 as keyof typeof PRIORITY_ORDER] ?? 3),
    },
    {
      field: "genetic_value_score",
      headerName: "Ovanliga gener (0–100)",
      width: 195,
      type: "number",
      valueFormatter: (value: number) => (value != null ? decimal(value) : "–"),
      renderHeader: () => (
        <HelpTooltip tooltip={RARE_GENES}>Ovanliga gener (0–100)</HelpTooltip>
      ),
    },
    {
      field: "genome_uniqueness",
      headerName: "Unika gener",
      width: 125,
      type: "number",
      valueFormatter: (value: number) => (value != null ? percent(value) : "–"),
      renderHeader: () => (
        <HelpTooltip tooltip={UNIQUE_GENES}>Unika gener</HelpTooltip>
      ),
    },
    {
      field: "reasons",
      headerName: "Skäl",
      flex: 1,
      minWidth: 260,
      cellClassName: "skal",
      valueFormatter: (value: string[], row) =>
        Array.isArray(value)
          ? translateReasons(value, row.individual_id).join("; ") // the reasons contain commas
          : "",
    },
  ];

  if (isLoading) {
    return (
      <Box>
        <Alert severity="info" sx={{ mb: 4 }}>
          Beräknar genetiska prioriteringar — detta kan ta upp till en minut.
        </Alert>
        <Skeleton variant="rounded" height={400} />
      </Box>
    );
  }

  if (error) {
    return <GeneticsError error={error} onRetry={refetch} />;
  }

  return (
    <Box>
      <GeneticsInfoPanel tab="priorities" />
      <Box
        sx={{
          mb: 2,
          display: "flex",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        {(
          Object.keys(priorityConfig) as Array<keyof typeof priorityConfig>
        ).map((level) => {
          const on = filters[level as keyof typeof filters];
          return (
            <FilterChip
              key={level}
              label={`${priorityConfig[level].label} (${
                priorities?.filter((p) => p.priority === level).length || 0
              })`}
              color={on ? priorityConfig[level].chipColor : "default"}
              variant={on ? "filled" : "outlined"}
              icon={
                on ? (
                  <CheckIcon sx={{ "&&": { color: "inherit" } }} />
                ) : undefined
              }
              aria-pressed={on}
              sx={on ? readableChip : chipOff}
              onClick={() => toggleFilter(level as keyof typeof filters)}
            />
          );
        })}
        {/* Left, after the chips: the fixed Tyck till tab covers the right edge. */}
        <Box sx={{ display: "flex", gap: 2, mb: 2, ml: { sm: 1 } }}>
          <button
            type="button"
            className={`sb-btn sb-btn-sm${perHerd ? "" : " sb-btn-secondary"}`}
            aria-pressed={perHerd}
            onClick={() => {
              setSortModel(perHerd ? [{ field: "priority", sort: "asc" }] : []);
              setPerHerd(!perHerd);
            }}
          >
            Sortera per besättning
          </button>
          <button
            type="button"
            className="sb-btn sb-btn-sm sb-btn-secondary"
            disabled={filteredRows.length === 0}
            onClick={async () => {
              // The server builds the file and logs the download (who, which rabbits).
              const refused = exportRefusal(mode, readModeCookieClient());
              setExportError(refused);
              if (refused) return;
              const url = prioritiesCsvUrl(
                genebankId,
                (Object.keys(filters) as Array<keyof typeof filters>).filter(
                  (level) => filters[level],
                ),
                perHerd,
              );
              setExportError(await downloadExport(url));
            }}
          >
            Ladda ner CSV
          </button>
        </Box>
      </Box>
      {exportError && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {exportError}
        </Alert>
      )}
      <Typography
        variant="body2"
        color="textSecondary"
        sx={{ display: { xs: "block", sm: "none" }, mb: 1 }}
      >
        Tabellen är bredare än skärmen. Dra i sidled för att se alla kolumner.
      </Typography>
      <Box sx={{ width: "100%" }}>
        <DataGrid
          rows={filteredRows}
          columns={columns}
          // As tall as its page of rows: the page scrolls, not a box inside the table.
          autoHeight
          initialState={{
            pagination: { paginationModel: { pageSize: 25, page: 0 } },
          }}
          sortModel={sortModel}
          onSortModelChange={(model) => {
            setSortModel(model);
            if (model.length > 0) setPerHerd(false);
          }}
          // Skäl wraps instead of being cut off, so each row is as tall as its reasons.
          getRowHeight={() => "auto"}
          sx={{
            "& .skal": { whiteSpace: "normal", lineHeight: 1.45, py: 1 },
          }}
          pageSizeOptions={[10, 25, 50]}
          // The chips are the only filter. The CSV holds the chips' levels in the list's order
          // (or per besättning), not in the order of a sort by clicking a column header.
          disableColumnFilter
          disableRowSelectionOnClick
          localeText={{
            noRowsLabel: "Inga kaniner att visa",
            paginationRowsPerPage: "Rader per sida:",
            paginationItemAriaLabel: (type) =>
              type === "first"
                ? "Gå till första sidan"
                : type === "last"
                  ? "Gå till sista sidan"
                  : type === "next"
                    ? "Gå till nästa sida"
                    : "Gå till föregående sida",
            paginationDisplayedRows: ({ from, to, count }) =>
              `${from}–${to} av ${count !== -1 ? count : `fler än ${to}`}`,
          }}
        />
      </Box>
    </Box>
  );
};

export default PrioritiesTab;
