"use client";

import React from "react";
import { Autocomplete, Box, TextField, Typography } from "@mui/material";
import type { ColorOption } from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";

interface ColorPickerProps {
  options: ColorOption[];
  /** The colour NAME; the backend resolves it within the genebank. */
  value: string;
  onChange: (name: string) => void;
  genebank: string;
  label?: string;
  required?: boolean;
}

/** Pick the genebank's list out of the /colors record: by name, else by herd prefix. */
export function colorsFor(
  all: Record<string, ColorOption[]> | null,
  genebank: string | undefined,
  herdId: string,
): ColorOption[] {
  if (!all) return [];
  if (genebank && all[genebank]) return all[genebank];
  const key =
    Object.keys(all).find((k) =>
      herdId.startsWith("M") ? k.includes("Mellerud") : k.includes("Gotland"),
    ) ?? Object.keys(all)[0];
  return all[key] ?? [];
}

const optionLabel = (c: ColorOption) => `${c.id} ${c.name}`;

export function ColorPicker({
  options,
  value,
  onChange,
  genebank,
  label = "Färg",
  required,
}: ColorPickerProps) {
  // Free text when no official list could be loaded; the backend validates either way.
  if (options.length === 0) {
    return (
      <TextField
        label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        size="small"
        fullWidth
        required={required}
      />
    );
  }

  return (
    <Autocomplete
      options={options}
      value={options.find((o) => o.name === value) ?? null}
      onChange={(_, v) => onChange(v?.name ?? "")}
      getOptionLabel={optionLabel}
      isOptionEqualToValue={(a, b) => a.id === b.id}
      size="small"
      fullWidth
      data-genebank={genebank}
      renderOption={({ key, ...props }, c) => (
        <li key={key} {...props}>
          <Box sx={{ minWidth: 0 }}>
            <Typography variant="body2">{optionLabel(c)}</Typography>
            {c.comment && (
              <Typography
                variant="caption"
                sx={{ color: "text.secondary", display: "block" }}
              >
                {c.comment}
              </Typography>
            )}
          </Box>
        </li>
      )}
      renderInput={(params) => (
        <TextField {...params} label={label} required={required} />
      )}
    />
  );
}
