"use client";

import React from "react";
import { Card, CardContent, Typography, TextField, Box } from "@mui/material";
import type { Individual } from "@/redux/api/apiSlice";

interface NotesSectionProps {
  individual: Individual;
  isEditing: boolean;
  formData: Partial<Individual>;
  onFieldChange: (field: string, value: string | null) => void;
}

export function NotesSection({
  individual,
  isEditing,
  formData,
  onFieldChange,
}: NotesSectionProps) {
  const notes = "notes" in formData ? formData.notes : individual.notes;
  const deathNote = individual.death_note;
  const hasContent = notes || deathNote;

  return (
    <Card>
      <CardContent>
        <Typography variant="h6" gutterBottom>
          Anteckningar
        </Typography>

        {isEditing ? (
          <TextField
            label="Anteckningar"
            value={notes || ""}
            onChange={(e) => onFieldChange("notes", e.target.value)}
            fullWidth
            multiline
            minRows={3}
            size="small"
          />
        ) : hasContent ? (
          <Box>
            {notes && (
              <Typography
                variant="body2"
                sx={{
                  mb: 1,
                }}
              >
                {notes}
              </Typography>
            )}
            {deathNote && (
              <Box
                sx={{
                  mt: 1,
                }}
              >
                <Typography
                  variant="caption"
                  sx={{
                    color: "text.secondary",
                  }}
                >
                  Dödsorsak
                </Typography>
                <Typography
                  variant="body2"
                  sx={{
                    color: "error.main",
                  }}
                >
                  {deathNote}
                </Typography>
              </Box>
            )}
          </Box>
        ) : (
          <Typography
            variant="body2"
            sx={{
              color: "text.secondary",
            }}
          >
            Inga anteckningar.
          </Typography>
        )}
      </CardContent>
    </Card>
  );
}
