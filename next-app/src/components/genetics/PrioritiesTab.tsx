import React, { useMemo, useState } from "react";
import styled from "@emotion/styled";

import { Box, Chip as MuiChip, Skeleton, Alert } from "@mui/material";
import { DataGrid, GridColDef } from "@mui/x-data-grid";

import {
  useFetchGeneticPrioritiesQuery,
  GeneticPriority,
} from "@/redux/api/apiSlice";
import { decimal, percent } from "@/lib/genetics";
import HelpTooltip from "./HelpTooltip";
import GeneticsInfoPanel from "./GeneticsInfoPanel";
import GeneticsError from "./GeneticsError";
import { readableChip } from "./readableChip";
import { translateReasons } from "@/utils/translateReasons";

const RARE_GENES =
  "Hur stor andel av kaninerna i beräkningen som är mer släkt med resten än den här kaninen. 100 betyder minst släkt, alltså mest ovanliga gener.";
const UNIQUE_GENES =
  "Sannolikheten att kaninen bär genvarianter från founderdjuren som ingen annan kanin i beräkningen bär, enligt en simulering av hur generna ärvs genom stamtavlan.";

const FilterChip = styled(MuiChip)<{ selected: boolean }>`
  margin-right: ${(props) => props.theme.spacing(1)};
  margin-bottom: ${(props) => props.theme.spacing(2)};
  opacity: ${(props) => (props.selected ? 1 : 0.5)};
`;

const priorityConfig: Record<
  string,
  { label: string; chipColor: "error" | "warning" | "default" }
> = {
  critical: { label: "Högsta", chipColor: "error" },
  important: { label: "Hög", chipColor: "warning" },
  normal: { label: "Övriga", chipColor: "default" },
};

interface PrioritiesTabProps {
  genebankId: number;
}

const PrioritiesTab = ({ genebankId }: PrioritiesTabProps) => {
  const {
    data: priorities,
    isLoading,
    error,
    refetch,
  } = useFetchGeneticPrioritiesQuery(genebankId);

  const [filters, setFilters] = useState({
    critical: true,
    important: true,
    normal: true,
  });

  const toggleFilter = (level: keyof typeof filters) => {
    setFilters((prev) => ({ ...prev, [level]: !prev[level] }));
  };

  const filteredRows = useMemo(() => {
    if (!priorities) return [];
    return priorities
      .filter((p) => filters[p.priority as keyof typeof filters])
      .map((p, index) => ({ ...p, id: p.individual_id || index }));
  }, [priorities, filters]);

  const columns: GridColDef[] = [
    {
      field: "individual_id",
      headerName: "Individnummer",
      width: 150,
    },
    {
      field: "priority",
      headerName: "Avelsprioritet",
      width: 180,
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
      sortComparator: (v1, v2) => {
        const order = { critical: 0, important: 1, normal: 2 };
        return (
          (order[v1 as keyof typeof order] ?? 3) -
          (order[v2 as keyof typeof order] ?? 3)
        );
      },
    },
    {
      field: "genetic_value_score",
      headerName: "Ovanliga gener (0–100)",
      width: 190,
      type: "number",
      valueFormatter: (value: number) => (value != null ? decimal(value) : "–"),
      renderHeader: () => (
        <HelpTooltip tooltip={RARE_GENES}>Ovanliga gener (0–100)</HelpTooltip>
      ),
    },
    {
      field: "genome_uniqueness",
      headerName: "Unika gener",
      width: 140,
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
      minWidth: 200,
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
        }}
      >
        {(
          Object.keys(priorityConfig) as Array<keyof typeof priorityConfig>
        ).map((level) => (
          <FilterChip
            key={level}
            label={`${priorityConfig[level].label} (${
              priorities?.filter((p) => p.priority === level).length || 0
            })`}
            color={priorityConfig[level].chipColor}
            sx={readableChip}
            selected={filters[level as keyof typeof filters]}
            onClick={() => toggleFilter(level as keyof typeof filters)}
            variant={
              filters[level as keyof typeof filters] ? "filled" : "outlined"
            }
          />
        ))}
      </Box>
      <Box sx={{ height: 600, width: "100%" }}>
        <DataGrid
          rows={filteredRows}
          columns={columns}
          initialState={{
            pagination: { paginationModel: { pageSize: 25, page: 0 } },
            sorting: {
              sortModel: [{ field: "priority", sort: "asc" }],
            },
          }}
          pageSizeOptions={[10, 25, 50]}
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
