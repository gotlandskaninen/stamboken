"use client";

import React, { useState } from "react";
import {
  Autocomplete,
  Box,
  Chip,
  CircularProgress,
  TextField,
} from "@mui/material";
import {
  useFetchIndividualsQuery,
  type PaginatedIndividualItem,
} from "@/redux/api/apiSlice";
import { useDebounce } from "@/hooks/useDebounce";

interface IndividualAutocompleteProps {
  label: string;
  sex: "male" | "female";
  genebankId?: number | null;
  herdId?: string;
  /**
   * With `herdId`: restrict to individuals that have ever been in that herd
   * (true), or search the whole genebank and merely list the herd's own first
   * (false). Defaults to the long-standing behaviour: true for females.
   */
  includeHistorical?: boolean;
  value: PaginatedIndividualItem | null;
  onChange: (value: PaginatedIndividualItem | null) => void;
  error?: boolean;
  helperText?: string;
  required?: boolean;
}

const statusColors: Record<
  string,
  "success" | "default" | "error" | "warning"
> = {
  active: "success",
  inactive: "warning",
  död: "error",
  slaktad: "error",
  avlivad: "error",
  försvunnen: "error",
};

/**
 * Async Autocomplete for selecting individuals from the paginated API.
 * Searches server-side with debounce, shows status badges, sorts herd's own first.
 */
export function IndividualAutocomplete({
  label,
  sex,
  genebankId,
  herdId,
  includeHistorical = sex === "female",
  value,
  onChange,
  error,
  helperText,
  required,
}: IndividualAutocompleteProps) {
  const [inputValue, setInputValue] = useState("");
  const debouncedSearch = useDebounce(inputValue, 300);

  const { data, isFetching } = useFetchIndividualsQuery(
    {
      sex,
      search: debouncedSearch,
      genebank_id: genebankId,
      herd_id: herdId,
      include_historical: includeHistorical,
      per_page: 20,
      sort: "name",
      order: "asc",
    },
    { skip: !genebankId },
  );

  // Sort active individuals first for breeding selection — keeps dead/inactive
  // rabbits available but visually deprioritized alongside the opacity styling.
  const options = [...(data?.items || [])].sort((a, b) => {
    if (a.status === "active" && b.status !== "active") return -1;
    if (a.status !== "active" && b.status === "active") return 1;
    return 0;
  });

  const getOptionLabel = (option: PaginatedIndividualItem) =>
    `${option.number}${option.name ? ` – ${option.name}` : ""}`;

  return (
    <Autocomplete
      options={options}
      getOptionLabel={getOptionLabel}
      value={value}
      onChange={(_, newValue) => onChange(newValue)}
      openOnFocus
      inputValue={inputValue}
      onInputChange={(_, newInputValue) => setInputValue(newInputValue)}
      loading={isFetching}
      noOptionsText={isFetching ? "Söker..." : "Skriv för att söka"}
      filterOptions={(x) => x} // Server-side filtering, don't filter client-side
      isOptionEqualToValue={(opt, val) => opt.number === val.number}
      renderOption={(props, option) => {
        const { key, ...rest } = props as any;
        const isOwnHerd = herdId && option.herd === herdId;
        return (
          <Box
            component="li"
            key={option.number}
            {...rest}
            sx={{ display: "flex", justifyContent: "space-between", gap: 1 }}
          >
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Box
                component="span"
                sx={{
                  fontWeight: isOwnHerd ? "bold" : "normal",
                  opacity: option.status === "active" ? 1 : 0.6,
                }}
              >
                {option.name || option.number}
              </Box>
              <Box
                component="span"
                sx={{ ml: 1, color: "text.secondary", fontSize: "0.8em" }}
              >
                {option.number}
                {!isOwnHerd && option.herd ? ` · ${option.herd}` : ""}
              </Box>
            </Box>
            <Chip
              label={option.status}
              size="small"
              color={statusColors[option.status] || "default"}
              variant={isOwnHerd ? "filled" : "outlined"}
              sx={{ fontSize: "0.7em", height: 20 }}
            />
          </Box>
        );
      }}
      renderInput={(params) => (
        <TextField
          {...params}
          label={label}
          error={error}
          helperText={helperText}
          required={required}
          slotProps={{
            ...params.slotProps,

            input: {
              ...params.slotProps.input,
              endAdornment: (
                <>
                  {isFetching ? (
                    <CircularProgress color="inherit" size={20} />
                  ) : null}
                  {params.slotProps.input.endAdornment}
                </>
              ),
            },
          }}
        />
      )}
    />
  );
}
