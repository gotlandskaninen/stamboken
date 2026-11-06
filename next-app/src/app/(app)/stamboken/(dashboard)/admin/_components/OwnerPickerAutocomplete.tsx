"use client";

import { Autocomplete, TextField } from "@mui/material";

export interface UserOption {
  id: number;
  username: string;
  fullname: string;
}

/**
 * User picker for gb-manager assign.
 * Autocompletes on username/fullname; the SELECTED OPTION carries the numeric
 * user id — callers submit `value.id`, never free text ("admins
 * never type raw integers").
 */
export function OwnerPickerAutocomplete({
  users,
  value,
  onChange,
  label = "Ny ägare",
  helperText,
}: {
  users: UserOption[];
  value: UserOption | null;
  onChange: (value: UserOption | null) => void;
  label?: string;
  helperText?: string;
}) {
  return (
    <Autocomplete
      options={users}
      value={value}
      onChange={(_, newValue) => onChange(newValue)}
      getOptionLabel={(o) =>
        o.fullname ? `${o.username} – ${o.fullname}` : o.username
      }
      isOptionEqualToValue={(opt, val) => opt.id === val.id}
      noOptionsText="Inga träffar"
      renderInput={(params) => (
        <TextField {...params} label={label} helperText={helperText} />
      )}
    />
  );
}
