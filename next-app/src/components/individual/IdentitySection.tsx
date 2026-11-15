"use client";

import React, { useEffect, useState } from "react";
import {
  Card,
  CardContent,
  Typography,
  Box,
  TextField,
  Grid,
} from "@mui/material";
import type { Individual } from "@/redux/api/apiSlice";
import { ColorPicker, colorsFor } from "@/components/herd/ColorPicker";
import {
  getColors,
  type ColorOption,
} from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";

interface IdentitySectionProps {
  individual: Individual;
  isEditing: boolean;
  formData: Partial<Individual>;
  onFieldChange: (field: string, value: string | null) => void;
}

interface FieldRowProps {
  label: string;
  value: string | null | undefined;
  field?: string;
  isEditing: boolean;
  formData: Partial<Individual>;
  onFieldChange: (field: string, value: string | null) => void;
  disabled?: boolean;
}

function FieldRow({
  label,
  value,
  field,
  isEditing,
  formData,
  onFieldChange,
  disabled,
}: FieldRowProps) {
  const displayValue =
    field && field in formData
      ? (formData as Record<string, any>)[field]
      : value;

  if (isEditing && field && !disabled) {
    return (
      <TextField
        label={label}
        value={displayValue || ""}
        onChange={(e) => onFieldChange(field, e.target.value)}
        fullWidth
        size="small"
        margin="none"
      />
    );
  }

  return (
    <Box>
      <Typography
        variant="caption"
        component="span"
        sx={{
          color: "text.secondary",
          mr: 0.5,
        }}
      >
        {label}:
      </Typography>
      <Typography variant="body2" component="span">
        {displayValue || "—"}
      </Typography>
    </Box>
  );
}

export function IdentitySection({
  individual,
  isEditing,
  formData,
  onFieldChange,
}: IdentitySectionProps) {
  const [colorOptions, setColorOptions] = useState<ColorOption[]>([]);
  useEffect(() => {
    if (!isEditing) return;
    getColors().then((all) =>
      setColorOptions(
        colorsFor(
          all,
          individual.genebank,
          typeof individual.herd === "string"
            ? individual.herd
            : individual.herd.herd,
        ),
      ),
    );
  }, [isEditing, individual.genebank, individual.herd]);

  const colorName = "color" in formData ? formData.color : individual.color;
  const colorDisplay =
    colorName && individual.color_id && colorName === individual.color
      ? `${individual.color_id} ${colorName}`
      : colorName;

  return (
    <Card>
      <CardContent sx={{ "&:last-child": { pb: 2 } }}>
        <Typography variant="h6" gutterBottom>
          Identitet
        </Typography>

        <Grid container spacing={isEditing ? 2 : 1}>
          <Grid size={{ xs: 6, sm: 4 }}>
            {isEditing ? (
              <ColorPicker
                options={colorOptions}
                value={colorName ?? ""}
                onChange={(name) => onFieldChange("color", name)}
                genebank={individual.genebank ?? ""}
              />
            ) : (
              <FieldRow
                label="Färg"
                value={colorDisplay}
                isEditing={false}
                formData={formData}
                onFieldChange={onFieldChange}
              />
            )}
          </Grid>
          <Grid size={{ xs: 6, sm: 4 }}>
            <FieldRow
              label="Ögonfärg"
              value={individual.eye_color}
              field="eye_color"
              isEditing={isEditing}
              formData={formData}
              onFieldChange={onFieldChange}
            />
          </Grid>
          <Grid size={{ xs: 6, sm: 4 }}>
            <FieldRow
              label="Klofärg"
              value={individual.claw_color}
              field="claw_color"
              isEditing={isEditing}
              formData={formData}
              onFieldChange={onFieldChange}
            />
          </Grid>
          <Grid size={{ xs: 6, sm: 4 }}>
            <FieldRow
              label="Bukfärg"
              value={individual.belly_color}
              field="belly_color"
              isEditing={isEditing}
              formData={formData}
              onFieldChange={onFieldChange}
            />
          </Grid>
          <Grid size={{ xs: 6, sm: 4 }}>
            <FieldRow
              label="Hårlag"
              value={individual.hair_notes}
              field="hair_notes"
              isEditing={isEditing}
              formData={formData}
              onFieldChange={onFieldChange}
            />
          </Grid>
          <Grid size={{ xs: 6, sm: 4 }}>
            <FieldRow
              label="Färganteckning"
              value={individual.color_note}
              field="color_note"
              isEditing={isEditing}
              formData={formData}
              onFieldChange={onFieldChange}
            />
          </Grid>
        </Grid>
      </CardContent>
    </Card>
  );
}
