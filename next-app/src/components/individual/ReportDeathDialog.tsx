"use client";

import React from "react";
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  TextField,
  Typography,
  Box,
  Alert,
  FormControlLabel,
  Checkbox,
} from "@mui/material";
import { DatePicker } from "@mui/x-date-pickers/DatePicker";
import { format, isValid } from "date-fns";
import { useTranslation } from "react-i18next";

interface ReportDeathDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: (
    deathDate: string | null,
    deathNote: string | null,
    butchered: boolean,
  ) => void;
  individualName: string;
  individualNumber: string;
  isSaving: boolean;
}

export function ReportDeathDialog({
  open,
  onClose,
  onConfirm,
  individualName,
  individualNumber,
  isSaving,
}: ReportDeathDialogProps) {
  const { t } = useTranslation();
  const today = new Date();
  const [deathDate, setDeathDate] = React.useState<Date | null>(today);
  const [deathNote, setDeathNote] = React.useState("");
  const [butchered, setButchered] = React.useState(false);

  const handleConfirm = () => {
    const dateStr =
      deathDate && isValid(deathDate) ? format(deathDate, "yyyy-MM-dd") : null;
    onConfirm(dateStr, deathNote || null, butchered);
  };

  const handleClose = () => {
    setDeathDate(new Date());
    setDeathNote("");
    setButchered(false);
    onClose();
  };

  const displayName = individualName || individualNumber;

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="sm"
      fullWidth
      aria-labelledby="report-death-title"
    >
      <DialogTitle id="report-death-title">
        {t("individual.death.reportTitle")}
      </DialogTitle>
      <DialogContent>
        <Alert severity="warning" sx={{ mb: 3 }}>
          <Typography variant="body2">
            {t("individual.death.warning", { name: displayName })}
          </Typography>
        </Alert>

        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            gap: 2.5,
            mt: 1,
          }}
        >
          <DatePicker
            label={t("individual.edit.deathDate")}
            value={deathDate}
            onChange={setDeathDate}
            maxDate={today}
            format="yyyy-MM-dd"
            slotProps={{
              textField: { size: "small", fullWidth: true },
              actionBar: { actions: ["today", "clear"] },
            }}
          />
          <TextField
            label={t("individual.edit.deathNote")}
            value={deathNote}
            onChange={(e) => setDeathNote(e.target.value)}
            fullWidth
            multiline
            minRows={2}
            size="small"
            placeholder={t("individual.death.notePlaceholder")}
          />
          <FormControlLabel
            control={
              <Checkbox
                checked={butchered}
                onChange={(e) => setButchered(e.target.checked)}
              />
            }
            label={t("individual.death.butcheredLabel")}
          />
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={handleClose} disabled={isSaving}>
          {t("common.cancel")}
        </Button>
        <Button
          onClick={handleConfirm}
          color="error"
          variant="contained"
          disabled={isSaving}
        >
          {isSaving
            ? t("individual.edit.saving")
            : t("individual.death.confirmButton")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
