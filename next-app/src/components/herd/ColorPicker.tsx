"use client";

import React, { useState } from "react";
import {
  Autocomplete,
  Box,
  Button,
  createFilterOptions,
  TextField,
  Typography,
} from "@mui/material";
import type { ColorOption } from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";
import { FargKortDialog } from "@/components/fargatlas/FargKortDialog";

interface ColorPickerProps {
  options: ColorOption[];
  /** The colour NAME; the backend resolves it within the genebank. */
  value: string;
  onChange: (name: string) => void;
  /** The stored colour's number, shown when the name is not on the list. */
  valueId?: number | null;
  /** The list is still loading: show the combobox, not the free-text fallback. */
  loading?: boolean;
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

const optionLabel = (c: ColorOption) =>
  c.id != null ? `${c.id} ${c.name}` : c.name;

// Search the comment too (synonyms such as havanna, hargrå, tricolor).
const filter = createFilterOptions<ColorOption>({
  stringify: (c) => `${optionLabel(c)} ${c.comment ?? ""}`,
});

export function ColorPicker({
  options,
  value,
  onChange,
  valueId,
  loading,
  genebank,
  label = "Färg",
  required,
}: ColorPickerProps) {
  const [showColor, setShowColor] = useState(false);
  // Free text when no official list could be loaded; the backend validates either way.
  if (options.length === 0 && !loading) {
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

  // A stored colour that is not on this list stays selected instead of vanishing.
  // With a stored id, the name alone is not enough: two genebanks both have an Albino.
  const found = options.find(
    (o) => o.name === value && (valueId == null || o.id === valueId),
  );
  const selected =
    found ??
    (value
      ? ({ id: valueId, name: value, comment: null } as unknown as ColorOption)
      : null);
  const shown = !found && selected ? [selected, ...options] : options;

  return (
    // Full width in a flex row (Registrera kanin) as the bare Autocomplete was, without growing in a flex column
    <Box sx={{ width: "100%", minWidth: 0 }}>
      <Autocomplete
        options={shown}
        value={selected as ColorOption}
        disableClearable
        loading={loading}
        filterOptions={filter}
        onChange={(_, v) => onChange(v.name)}
        getOptionLabel={optionLabel}
        isOptionEqualToValue={(a, b) =>
          a.name === b.name && (a.id == null || b.id == null || a.id === b.id)
        }
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
      {selected?.id != null && (
        <>
          <Button
            size="small"
            onClick={() => setShowColor(true)}
            sx={{ minHeight: 44, px: 0 }}
          >
            Visa färgen
          </Button>
          <FargKortDialog
            id={selected.id}
            open={showColor}
            onClose={() => setShowColor(false)}
          />
        </>
      )}
    </Box>
  );
}
