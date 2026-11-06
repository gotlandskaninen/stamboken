import React, { useMemo, useState } from "react";
import styled from "@emotion/styled";

import { Box, Chip as MuiChip, Skeleton, Alert } from "@mui/material";
import { DataGrid, GridColDef } from "@mui/x-data-grid";
import { red, orange, grey } from "@mui/material/colors";

import {
  useFetchGeneticPrioritiesQuery,
  GeneticPriority,
} from "@/redux/api/apiSlice";
import HelpTooltip from "./HelpTooltip";
import GeneticsInfoPanel from "./GeneticsInfoPanel";
import { translateReasons } from "@/utils/translateReasons";

const FilterChip = styled(MuiChip)<{ selected: boolean }>`
  margin-right: ${(props) => props.theme.spacing(1)};
  margin-bottom: ${(props) => props.theme.spacing(2)};
  opacity: ${(props) => (props.selected ? 1 : 0.5)};
`;

const priorityConfig: Record<
  string,
  { label: string; color: string; chipColor: "error" | "warning" | "default" }
> = {
  critical: { label: "Kritisk", color: red[500], chipColor: "error" },
  important: { label: "Viktig", color: orange[500], chipColor: "warning" },
  normal: { label: "Normal", color: grey[500], chipColor: "default" },
};

interface PrioritiesTabProps {
  genebankId: number;
}

const PrioritiesTab = ({ genebankId }: PrioritiesTabProps) => {
  const {
    data: priorities,
    isLoading,
    error,
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
      headerName: "Individ",
      width: 150,
    },
    {
      field: "priority",
      headerName: "Prioritet",
      width: 130,
      renderCell: (params) => {
        const config = priorityConfig[params.value] || priorityConfig.normal;
        return (
          <MuiChip label={config.label} color={config.chipColor} size="small" />
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
      headerName: "Genetiskt värde",
      description:
        "Inverterad MK-percentil (0–100). Högt = låg MK = genetiskt värdefullt.",
      width: 140,
      type: "number",
      valueFormatter: (value: number) => value?.toFixed(1),
      renderHeader: () => (
        <HelpTooltip tooltip="Inverterad MK-percentil (0–100). Högt = låg MK = genetiskt värdefullt.">
          Genetiskt värde
        </HelpTooltip>
      ),
    },
    {
      field: "genome_uniqueness",
      headerName: "Genomunikhet",
      description:
        "Sannolikhet att individen bär alleler som inte finns hos andra. Från gene drop-simulering.",
      width: 140,
      type: "number",
      valueFormatter: (value: number) =>
        value != null ? `${(value * 100).toFixed(1)}%` : "-",
      renderHeader: () => (
        <HelpTooltip tooltip="Sannolikhet att individen bär unika alleler. Från gene drop-simulering.">
          Genomunikhet
        </HelpTooltip>
      ),
    },
    {
      field: "reasons",
      headerName: "Skäl",
      flex: 1,
      minWidth: 200,
      valueFormatter: (value: string[]) =>
        Array.isArray(value) ? translateReasons(value).join(", ") : "",
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

  const isAuthError =
    error != null &&
    typeof error === "object" &&
    "status" in error &&
    (error as { status: unknown }).status === 401;

  if (error && !isAuthError) {
    return (
      <Alert severity="error">
        Kunde inte hämta prioriteringsdata. Kontrollera att du har behörighet.
      </Alert>
    );
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
            noRowsLabel: "Inga individer att visa",
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
