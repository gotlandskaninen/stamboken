"use client";

import React, { useState, useEffect, useCallback } from "react";
import {
  Box,
  Button,
  TextField,
  CircularProgress,
  Typography,
  Grid,
  Divider,
} from "@mui/material";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { LocalizationProvider } from "@mui/x-date-pickers/LocalizationProvider";
import { AdapterDateFns } from "@mui/x-date-pickers/AdapterDateFns";
import { sv } from "date-fns/locale";
import { useTranslation } from "react-i18next";
import type { PaginatedIndividualItem } from "@/redux/api/apiSlice";
import { IndividualAutocomplete } from "@/components/herd/IndividualAutocomplete";

const STORAGE_KEY_PREFIX = "herdbook-litter-form-";
const GESTATION_DAYS = 31; // Middle of rabbit gestation window (26-38 days)

interface LitterFormData {
  mother: PaginatedIndividualItem | null;
  father: PaginatedIndividualItem | null;
  birthDate: Date | null;
  totalBorn: string;
  aliveAt6w: string;
  birthNotes: string;
}

export interface LitterSubmitData {
  mother: string;
  father: string;
  birthDate: string;
  breedingDate: string;
  totalBorn: number;
  aliveAt6w: number | null;
  birthNotes: string;
  breedingHerd: string;
}

interface LitterRegistrationFormProps {
  herdId: string;
  genebankId?: number | null;
  onSubmit: (data: LitterSubmitData) => Promise<boolean>;
  onCancel: () => void;
  isSubmitting?: boolean;
}

function getInitialFormData(herdId?: string): LitterFormData {
  try {
    const saved = localStorage.getItem(STORAGE_KEY_PREFIX + (herdId || ""));
    if (saved) {
      const parsed = JSON.parse(saved);
      return {
        // Restore saved selections as PaginatedIndividualItem stubs
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
        birthDate: parsed.birthDate ? new Date(parsed.birthDate) : new Date(),
        totalBorn: parsed.totalBorn || "",
        aliveAt6w: parsed.aliveAt6w || "",
        birthNotes: parsed.birthNotes || "",
      };
    }
  } catch {
    // Ignore localStorage errors
  }
  return {
    mother: null,
    father: null,
    birthDate: new Date(),
    totalBorn: "",
    aliveAt6w: "",
    birthNotes: "",
  };
}

function formatDate(d: Date): string {
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

export function LitterRegistrationForm({
  herdId,
  genebankId,
  onSubmit,
  onCancel,
  isSubmitting = false,
}: LitterRegistrationFormProps) {
  const { t } = useTranslation();
  const storageKey = STORAGE_KEY_PREFIX + herdId;
  const [formData, setFormData] = useState<LitterFormData>(() =>
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
          birthDate: formData.birthDate?.toISOString() || null,
          totalBorn: formData.totalBorn,
          aliveAt6w: formData.aliveAt6w,
          birthNotes: formData.birthNotes,
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
    if (!formData.birthDate) {
      newErrors.birthDate = "Födelsedatum krävs";
    }
    if (!formData.totalBorn || parseInt(formData.totalBorn) <= 0) {
      newErrors.totalBorn = "Antal födda måste vara större än 0";
    }

    // Parent birth date validation (FR15)
    if (formData.mother?.birth_date && formData.birthDate) {
      if (new Date(formData.mother.birth_date) >= formData.birthDate) {
        newErrors.mother = "Modern måste vara född före kullen";
      }
    }
    if (formData.father?.birth_date && formData.birthDate) {
      if (new Date(formData.father.birth_date) >= formData.birthDate) {
        newErrors.father = "Fadern måste vara född före kullen";
      }
    }

    // alive at 6w can't exceed total born
    if (formData.aliveAt6w && formData.totalBorn) {
      if (parseInt(formData.aliveAt6w) > parseInt(formData.totalBorn)) {
        newErrors.aliveAt6w =
          "Antal vid 6 veckor kan inte överstiga antal födda";
      }
    }

    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  }, [formData]);

  const isFormValid =
    !!formData.mother &&
    !!formData.father &&
    !!formData.birthDate &&
    !!formData.totalBorn &&
    parseInt(formData.totalBorn) > 0;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    const birthDate = formData.birthDate!;
    // Breeding date = birth date - gestation period (31 days, middle of 26-38 window)
    const breedingDate = new Date(birthDate);
    breedingDate.setDate(breedingDate.getDate() - GESTATION_DAYS);

    const success = await onSubmit({
      mother: formData.mother!.number,
      father: formData.father!.number,
      birthDate: formatDate(birthDate),
      breedingDate: formatDate(breedingDate),
      totalBorn: parseInt(formData.totalBorn),
      aliveAt6w: formData.aliveAt6w ? parseInt(formData.aliveAt6w) : null,
      birthNotes: formData.birthNotes,
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
          {t("breeding.newLitterTitle")}
        </Typography>
        <Typography
          variant="body2"
          sx={{
            color: "text.secondary",
            mb: 2,
          }}
        >
          {t("breeding.newLitterHelp")}
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

          {/* Birth date full width */}
          <Grid size={{ xs: 12 }}>
            <Divider sx={{ my: 1 }} />
          </Grid>
          <Grid size={{ xs: 12, sm: 6 }}>
            <DatePicker
              label={t("breeding.birthDate")}
              value={formData.birthDate}
              maxDate={new Date()}
              onChange={(value) =>
                setFormData((prev) => ({ ...prev, birthDate: value }))
              }
              slotProps={{
                textField: {
                  fullWidth: true,
                  required: true,
                  error: !!errors.birthDate,
                  helperText: errors.birthDate,

                  slotProps: {
                    htmlInput: { "aria-label": t("breeding.birthDate") },
                  },
                },
              }}
            />
          </Grid>

          {/* Litter counts side by side */}
          <Grid size={{ xs: 6, sm: 3 }}>
            <TextField
              label={t("breeding.totalBorn")}
              type="number"
              fullWidth
              value={formData.totalBorn}
              onChange={(e) =>
                setFormData((prev) => ({ ...prev, totalBorn: e.target.value }))
              }
              error={!!errors.totalBorn}
              helperText={errors.totalBorn}
              required
              slotProps={{
                htmlInput: { min: 1, "aria-label": t("breeding.totalBorn") },
              }}
            />
          </Grid>
          <Grid size={{ xs: 6, sm: 3 }}>
            <TextField
              label={t("breeding.aliveAt6w")}
              type="number"
              fullWidth
              value={formData.aliveAt6w}
              onChange={(e) =>
                setFormData((prev) => ({ ...prev, aliveAt6w: e.target.value }))
              }
              error={!!errors.aliveAt6w}
              helperText={errors.aliveAt6w}
              slotProps={{
                htmlInput: { min: 0, "aria-label": t("breeding.aliveAt6w") },
              }}
            />
          </Grid>

          {/* Notes full width */}
          <Grid size={{ xs: 12 }}>
            <TextField
              label={t("breeding.birthNotes")}
              value={formData.birthNotes}
              onChange={(e) =>
                setFormData((prev) => ({
                  ...prev,
                  birthNotes: e.target.value,
                }))
              }
              fullWidth
              multiline
              rows={2}
              slotProps={{
                htmlInput: { "aria-label": t("breeding.birthNotes") },
              }}
            />
          </Grid>
        </Grid>

        <Box
          sx={{
            display: "flex",
            gap: 2,
            justifyContent: "flex-end",
            mt: 2,
          }}
        >
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
              t("breeding.register")
            )}
          </Button>
        </Box>
      </Box>
    </LocalizationProvider>
  );
}
