"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Box,
  Button,
  TextField,
  CircularProgress,
  Typography,
  Grid,
} from "@mui/material";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDateFns } from "@mui/x-date-pickers/AdapterDateFns";
import { sv } from "date-fns/locale";
import NextLink from "next/link";
import { useTranslation } from "react-i18next";
import type { PaginatedIndividualItem } from "@/redux/api/apiSlice";
import { IndividualAutocomplete } from "@/components/herd/IndividualAutocomplete";
import { serializeProvparningParams } from "@/lib/provparning";

const STORAGE_KEY_PREFIX = "herdbook-mating-form-";

interface MatingFormData {
  mother: PaginatedIndividualItem | null;
  father: PaginatedIndividualItem | null;
  matingDate: Date | null;
  breedNotes: string;
}

export interface MatingSubmitData {
  mother: string;
  father: string;
  matingDate: string;
  breedNotes: string;
  breedingHerd: string;
}

interface MatingRegistrationFormProps {
  herdId: string;
  genebankId?: number | null;
  onSubmit: (data: MatingSubmitData) => Promise<boolean>;
  onCancel: () => void;
  isSubmitting?: boolean;
}

function getInitialFormData(herdId?: string): MatingFormData {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_PREFIX + (herdId || ""));
    if (saved) {
      const parsed = JSON.parse(saved);
      return {
        mother:
          parsed.motherNumber && parsed.motherName !== undefined
            ? {
                number: parsed.motherNumber,
                name: parsed.motherName,
                sex: "female",
                birth_date: null,
                status: "active",
                herd: "",
                color: null,
                has_photo: false,
                litter_size: null,
                litter_size6w: null,
                mother_number: null,
                mother_name: null,
                father_number: null,
                father_name: null,
              }
            : null,
        father:
          parsed.fatherNumber && parsed.fatherName !== undefined
            ? {
                number: parsed.fatherNumber,
                name: parsed.fatherName,
                sex: "male",
                birth_date: null,
                status: "active",
                herd: "",
                color: null,
                has_photo: false,
                litter_size: null,
                litter_size6w: null,
                mother_number: null,
                mother_name: null,
                father_number: null,
                father_name: null,
              }
            : null,
        matingDate: parsed.matingDate
          ? new Date(parsed.matingDate)
          : new Date(),
        breedNotes: parsed.breedNotes || "",
      };
    }
  } catch {
    // Ignore localStorage errors
  }
  return {
    mother: null,
    father: null,
    matingDate: new Date(),
    breedNotes: "",
  };
}

function formatDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function MatingRegistrationForm({
  herdId,
  genebankId,
  onSubmit,
  onCancel,
  isSubmitting = false,
}: MatingRegistrationFormProps) {
  const { t } = useTranslation();
  const storageKey = STORAGE_KEY_PREFIX + herdId;
  const [formData, setFormData] = useState<MatingFormData>(() =>
    getInitialFormData(herdId),
  );
  const [errors, setErrors] = useState<Record<string, string>>({});

  // Auto-save to localStorage on form changes
  useEffect(() => {
    try {
      localStorage.setItem(
        storageKey,
        JSON.stringify({
          motherNumber: formData.mother?.number || null,
          motherName: formData.mother?.name ?? null,
          fatherNumber: formData.father?.number || null,
          fatherName: formData.father?.name ?? null,
          matingDate: formData.matingDate?.toISOString() || null,
          breedNotes: formData.breedNotes,
        }),
      );
    } catch {
      // Ignore localStorage errors
    }
  }, [formData, storageKey]);

  const validate = useCallback((): boolean => {
    const newErrors: Record<string, string> = {};

    if (!formData.mother) {
      newErrors.mother = "Mor måste väljas";
    }
    if (!formData.father) {
      newErrors.father = "Far måste väljas";
    }
    if (!formData.matingDate) {
      newErrors.matingDate = "Parningsdatum krävs";
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [formData]);

  const isFormValid =
    !!formData.mother && !!formData.father && !!formData.matingDate;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    const success = await onSubmit({
      mother: formData.mother!.number,
      father: formData.father!.number,
      matingDate: formatDate(formData.matingDate!),
      breedNotes: formData.breedNotes,
      breedingHerd: herdId,
    });

    // Only clear localStorage after confirmed success
    if (success) {
      try {
        localStorage.removeItem(storageKey);
      } catch {
        // Ignore
      }
    }
  };

  // Test-mate the chosen pair first (the form is auto-saved, so nothing is lost).
  const testMateQuery = serializeProvparningParams({
    genebank: genebankId ?? null,
    hona: formData.mother?.number ?? null,
    hane: formData.father ? [formData.father.number] : [],
  });
  const testMateHref = `/stamboken/provparning${testMateQuery ? `?${testMateQuery}` : ""}`;

  return (
    <LocalizationProvider dateAdapter={AdapterDateFns} adapterLocale={sv}>
      <Box
        component="form"
        onSubmit={handleSubmit}
        sx={{
          border: 1,
          borderColor: "primary.main",
          borderRadius: 1,
          p: 3,
          backgroundColor: "background.paper",
        }}
      >
        <Typography
          variant="subtitle1"
          gutterBottom
          sx={{
            fontWeight: "bold",
          }}
        >
          {t("breeding.newMatingTitle")}
        </Typography>
        <Typography
          variant="body2"
          sx={{
            color: "text.secondary",
            mb: 2,
          }}
        >
          {t("breeding.newMatingHelp")}
        </Typography>

        <Grid container spacing={2}>
          {/* Parents side by side on desktop */}
          <Grid size={{ xs: 12, sm: 6 }}>
            <IndividualAutocomplete
              label={t("breeding.mother")}
              sex="female"
              genebankId={genebankId}
              herdId={herdId}
              value={formData.mother}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, mother: value }))
              }
              error={!!errors.mother}
              helperText={errors.mother}
              required
            />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <IndividualAutocomplete
              label={t("breeding.father")}
              sex="male"
              genebankId={genebankId}
              herdId={herdId}
              value={formData.father}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, father: value }))
              }
              error={!!errors.father}
              helperText={errors.father}
              required
            />
          </Grid>

          {/* Mating date */}
          <Grid size={{ xs: 12, sm: 6 }}>
            <DatePicker
              label={t("breeding.matingDate")}
              value={formData.matingDate}
              maxDate={new Date()}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, matingDate: value }))
              }
              slotProps={{
                textField: {
                  fullWidth: true,
                  required: true,
                  error: !!errors.matingDate,
                  helperText: errors.matingDate,

                  slotProps: {
                    htmlInput: { "aria-label": t("breeding.matingDate") },
                  },
                },
              }}
            />
          </Grid>

          {/* Notes full width */}
          <Grid size={{ xs: 12 }}>
            <TextField
              label={t("breeding.breedNotes")}
              value={formData.breedNotes}
              onChange={(e) =>
                setFormData((prev) => ({
                  ...prev,
                  breedNotes: e.target.value,
                }))
              }
              fullWidth
              multiline
              rows={2}
              slotProps={{
                htmlInput: { "aria-label": t("breeding.breedNotes") },
              }}
            />
          </Grid>
        </Grid>

        <Box
          sx={{
            display: "flex",
            flexWrap: "wrap",
            gap: 2,
            justifyContent: "flex-end",
            mt: 2,
          }}
        >
          <Button
            component={NextLink}
            href={testMateHref}
            disabled={isSubmitting}
            sx={{ minHeight: 48, mr: "auto" }}
          >
            Provpara först
          </Button>
          <Button
            onClick={onCancel}
            disabled={isSubmitting}
            sx={{ minHeight: 48 }}
          >
            {t("common.cancel")}
          </Button>
          <Button
            type="submit"
            variant="contained"
            disabled={!isFormValid || isSubmitting}
            sx={{ minHeight: 48, minWidth: 120 }}
          >
            {isSubmitting ? (
              <CircularProgress size={24} color="inherit" />
            ) : (
              t("breeding.registerMating")
            )}
          </Button>
        </Box>
      </Box>
    </LocalizationProvider>
  );
}
