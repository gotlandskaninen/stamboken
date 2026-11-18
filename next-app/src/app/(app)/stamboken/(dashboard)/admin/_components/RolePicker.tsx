"use client";

import { useState } from "react";
import {
  Autocomplete,
  Button,
  MenuItem,
  Stack,
  TextField,
} from "@mui/material";
import type { PrivilegeEntry } from "../_lib/types";

export type GenebankOption = { id: number; name: string };
export type HerdOption = { id: number; herd: string; herd_name: string | null };

type Level = PrivilegeEntry["level"];

/**
 * Grant-role picker. Level select + conditional secondary picker
 * (genebank for manager/helper/viewer, herd for owner). Submits NUMERIC ids —
 * `owner.herd` is the integer Herd.id primary key, never the "G12" code
 * Options arrive as props from the RSC page (no
 * client-side data fetching); MUI Autocomplete filters locally.
 */
export function RolePicker({
  genebanks,
  herds,
  disabled = false,
  defaultLevel = "viewer",
  onGrant,
}: {
  genebanks: GenebankOption[];
  herds: HerdOption[];
  disabled?: boolean;
  defaultLevel?: Level;
  onGrant: (role: PrivilegeEntry) => void;
}) {
  const [level, setLevel] = useState<Level>(defaultLevel);
  const [genebank, setGenebank] = useState<GenebankOption | null>(null);
  const [herd, setHerd] = useState<HerdOption | null>(null);

  const needsGenebank =
    level === "manager" || level === "helper" || level === "viewer";
  const needsHerd = level === "owner";
  const incomplete = (needsGenebank && !genebank) || (needsHerd && !herd);

  const submit = () => {
    if (level === "admin" || level === "matrikel_admin") {
      onGrant({ level });
    } else if (needsGenebank && genebank) {
      onGrant({ level, genebank: genebank.id });
    } else if (needsHerd && herd) {
      onGrant({ level: "owner", herd: herd.id });
    }
    setGenebank(null);
    setHerd(null);
  };

  return (
    <Stack
      direction={{ xs: "column", sm: "row" }}
      spacing={2}
      sx={{
        alignItems: "flex-start",
      }}
    >
      <TextField
        select
        size="small"
        label="Roll"
        value={level}
        sx={{ minWidth: 180 }}
        onChange={(e) => setLevel(e.target.value as Level)}
      >
        <MenuItem value="admin">Administratör</MenuItem>
        <MenuItem value="matrikel_admin">Matrikeladministratör</MenuItem>
        <MenuItem value="manager">Genbanksansvarig</MenuItem>
        <MenuItem value="helper">Genbankshjälpare</MenuItem>
        <MenuItem value="viewer">Granskare</MenuItem>
        <MenuItem value="owner">Besättningsägare</MenuItem>
      </TextField>
      {needsGenebank && (
        <Autocomplete
          size="small"
          sx={{ minWidth: 240 }}
          options={genebanks}
          getOptionLabel={(o) => o.name}
          isOptionEqualToValue={(a, b) => a.id === b.id}
          value={genebank}
          onChange={(_, v) => setGenebank(v)}
          renderInput={(params) => <TextField {...params} label="Genbank" />}
        />
      )}
      {needsHerd && (
        <Autocomplete
          size="small"
          sx={{ minWidth: 280 }}
          options={herds}
          getOptionLabel={(o) =>
            `${o.herd} — ${o.herd_name ?? "(namnlös besättning)"}`
          }
          isOptionEqualToValue={(a, b) => a.id === b.id}
          value={herd}
          onChange={(_, v) => setHerd(v)}
          renderInput={(params) => <TextField {...params} label="Besättning" />}
        />
      )}
      <Button
        variant="contained"
        onClick={submit}
        disabled={disabled || incomplete}
      >
        Lägg till roll
      </Button>
    </Stack>
  );
}
