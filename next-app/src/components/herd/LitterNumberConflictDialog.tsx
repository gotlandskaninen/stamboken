"use client";

import React from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import { useTranslation } from "react-i18next";

interface Conflict {
  breeding_id: number;
  current_litter_number: number;
  suggested_litter_number: number;
  birth_date: string;
  mother?: string | null;
  affected_individuals?: string[];
}

interface LitterNumberConflictDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  conflicts: Conflict[];
  isRenumbering: boolean;
  error?: string | null;
}

export function LitterNumberConflictDialog({
  open,
  onClose,
  onConfirm,
  conflicts,
  isRenumbering,
  error,
}: LitterNumberConflictDialogProps) {
  const { t } = useTranslation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));

  const totalAffected = conflicts.reduce(
    (sum, c) => sum + (c.affected_individuals?.length || 0),
    0,
  );

  // check-order conflicts only carry individual numbers (no certificate data),
  // so the paper-certificate warning stays disabled until the API exposes it.
  const hasPaperCerts = false;

  return (
    <Dialog
      open={open}
      onClose={isRenumbering ? undefined : onClose}
      maxWidth="md"
      fullWidth
      fullScreen={isMobile}
      aria-labelledby="conflict-dialog-title"
    >
      <DialogTitle id="conflict-dialog-title">
        {t("addRabbit.conflict.title")}
      </DialogTitle>
      <DialogContent>
        {error && (
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
        )}
        <Alert severity="warning" sx={{ mb: 2 }}>
          <Typography variant="body2">
            {t("addRabbit.conflict.message", {
              year: conflicts[0]?.birth_date?.substring(0, 4) || "?",
            })}
          </Typography>
        </Alert>

        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>{t("addRabbit.litterNumber")}</TableCell>
              <TableCell>{t("breeding.mother")}</TableCell>
              <TableCell>{t("breeding.birthDate")}</TableCell>
              <TableCell align="center">
                {t("addRabbit.conflict.newLitterNumber")}
              </TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {conflicts.map((c) => (
              <TableRow key={c.breeding_id}>
                <TableCell>{c.current_litter_number}</TableCell>
                <TableCell>{c.mother || "?"}</TableCell>
                <TableCell>{c.birth_date}</TableCell>
                <TableCell align="center">
                  {c.suggested_litter_number}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>

        {totalAffected > 0 && (
          <Box sx={{ mt: 2 }}>
            <Typography
              variant="body2"
              sx={{
                color: "text.secondary",
              }}
            >
              {t("addRabbit.conflict.affected", { count: totalAffected })}
            </Typography>
          </Box>
        )}

        {hasPaperCerts && (
          <Alert severity="info" sx={{ mt: 1 }}>
            {t("addRabbit.conflict.paperWarning", { count: 0 })}
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isRenumbering}>
          {t("common.cancel")}
        </Button>
        <Button
          onClick={onConfirm}
          variant="contained"
          disabled={isRenumbering}
          startIcon={
            isRenumbering ? (
              <CircularProgress size={16} color="inherit" />
            ) : null
          }
        >
          {t("addRabbit.conflict.renumber")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
