"use client";

import React from "react";
import { Box, Button, Typography, Paper } from "@mui/material";

interface EditSaveBarProps {
  isDirty: boolean;
  isSaving: boolean;
  onSave: () => void;
  onCancel: () => void;
}

export function EditSaveBar({
  isDirty,
  isSaving,
  onSave,
  onCancel,
}: EditSaveBarProps) {
  if (!isDirty) return null;

  return (
    <Paper
      role="status"
      aria-live="polite"
      elevation={3}
      sx={{
        position: "fixed",
        bottom: 0,
        left: 0,
        right: 0,
        zIndex: 1200,
        p: 2,
        pb: "calc(16px + env(safe-area-inset-bottom, 0px))",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        gap: 2,
        borderTop: 1,
        borderColor: "divider",
      }}
    >
      <Typography
        variant="body2"
        sx={{
          color: "text.secondary",
        }}
      >
        Osparade ändringar
      </Typography>
      <Button
        variant="outlined"
        size="medium"
        onClick={onCancel}
        disabled={isSaving}
      >
        Avbryt
      </Button>
      <Button
        variant="contained"
        size="medium"
        onClick={onSave}
        disabled={isSaving}
      >
        {isSaving ? "Sparar..." : "Spara"}
      </Button>
    </Paper>
  );
}
