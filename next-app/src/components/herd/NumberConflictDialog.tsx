"use client";

import React, { useState } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  TextField,
  Typography,
  useMediaQuery,
  useTheme,
} from "@mui/material";
import { useTranslation } from "react-i18next";
import Link from "next/link";
import type { NumberCheck } from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";

// The form of an individual number (G1274-2512): checked against Stamboken once typed
export const PAPER_NUMBER = /^[A-Za-z]+\d+-\d{4,}$/;

interface NumberConflictDialogProps {
  check: NumberCheck;
  /** "Pappret rättas": register again with Stamboken's number. */
  onUseStambokenNumber: () => void;
  onClose: () => void;
  isSaving: boolean;
}

/**
 * The paper certificate's individual number differs from Stamboken's (spec
 * 2026-10-30): what the paper says, what Stamboken says and why, then the two
 * choices with none preselected. Nothing is saved until the breeder chooses;
 * "Pappret stämmer" saves nothing and shows what the breeder must do.
 */
export function NumberConflictDialog({
  check,
  onUseStambokenNumber,
  onClose,
  isSaving,
}: NumberConflictDialogProps) {
  const { t } = useTranslation();
  const theme = useTheme();
  const isMobile = useMediaQuery(theme.breakpoints.down("sm"));
  const [paperIsRight, setPaperIsRight] = useState(false);
  const [copied, setCopied] = useState<number | null>(null);
  const canUseStamboken = check.choices.includes("use_stamboken_number");

  const copy = async (index: number, message: string) => {
    try {
      await navigator.clipboard.writeText(message);
      setCopied(index);
    } catch {
      setCopied(null); // the text stays selectable in the field
    }
  };

  return (
    <Dialog
      open
      onClose={isSaving ? undefined : onClose}
      maxWidth="sm"
      fullWidth
      fullScreen={isMobile}
      aria-labelledby="number-conflict-title"
    >
      <DialogTitle id="number-conflict-title">
        {t("numberConflict.title")}
      </DialogTitle>
      <DialogContent>
        <Box sx={{ display: "flex", flexDirection: "column", gap: 1.5 }}>
          <Typography variant="body1">
            {t("numberConflict.paperSays", { number: check.paper_number })}
          </Typography>
          <Typography variant="body1">
            {check.stamboken_number
              ? t("numberConflict.stambokenSays", {
                  number: check.stamboken_number,
                })
              : t("numberConflict.stambokenNone")}
          </Typography>
          <Box component="ul" sx={{ m: 0, pl: 2.5 }}>
            {check.conflicts.map((c, i) => {
              const holder = c.holder?.number
                ? `${c.holder.number} (${c.holder.herd})`
                : t("numberConflict.unknownHolder");
              const litter = c.holder?.litter
                ? c.holder.litter +
                  (c.holder.number ? ` (${c.holder.number})` : "")
                : t("numberConflict.noLitter");
              // A taken certificate number with the same parents is the same rabbit
              const kind =
                c.kind === "duplicate_rabbit" && c.paper
                  ? "duplicate_rabbit_certificate"
                  : c.kind;
              return (
                <Typography component="li" variant="body2" key={i}>
                  {t(`numberConflict.why.${kind}`, {
                    paper: c.paper,
                    stamboken: c.stamboken,
                    holder,
                    litter,
                    litterNumber: c.holder?.litter_number ?? "?",
                  })}
                </Typography>
              );
            })}
          </Box>

          {!paperIsRight && (
            <>
              <Alert severity="info">{t("numberConflict.nothingSaved")}</Alert>
              {canUseStamboken && check.stamboken_number && (
                <Box>
                  <Button
                    variant="outlined"
                    fullWidth
                    onClick={onUseStambokenNumber}
                    disabled={isSaving}
                    startIcon={
                      isSaving ? (
                        <CircularProgress size={16} color="inherit" />
                      ) : null
                    }
                  >
                    {t("numberConflict.useStamboken")}
                  </Button>
                  <Typography
                    variant="caption"
                    sx={{ color: "text.secondary" }}
                  >
                    {t("numberConflict.useStambokenHelp", {
                      number: check.stamboken_number,
                    })}
                  </Typography>
                </Box>
              )}
              <Box>
                <Button
                  variant="outlined"
                  fullWidth
                  onClick={() => setPaperIsRight(true)}
                  disabled={isSaving}
                >
                  {t("numberConflict.paperIsRight")}
                </Button>
                <Typography variant="caption" sx={{ color: "text.secondary" }}>
                  {t("numberConflict.paperIsRightHelp")}
                </Typography>
              </Box>
            </>
          )}

          {paperIsRight && (
            <Box sx={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <Alert severity="info">
                {t("numberConflict.nothingWritten")}
              </Alert>
              {check.actions.length === 0 && (
                <Typography variant="body2">
                  {t("numberConflict.contactManager")}
                </Typography>
              )}
              {check.actions.map((action, i) => (
                <Box
                  key={i}
                  sx={{ display: "flex", flexDirection: "column", gap: 1 }}
                >
                  <Typography variant="body2">{action.text}</Typography>
                  {action.self_service && (
                    <Button
                      component={Link}
                      href={action.self_service}
                      variant="text"
                      sx={{ alignSelf: "flex-start" }}
                    >
                      {t("numberConflict.selfService")}
                    </Button>
                  )}
                  {action.manager_message && (
                    <>
                      <TextField
                        label={t("numberConflict.managerMessage")}
                        value={action.manager_message}
                        multiline
                        minRows={3}
                        fullWidth
                        slotProps={{ htmlInput: { readOnly: true } }}
                      />
                      <Button
                        variant="outlined"
                        onClick={() => copy(i, action.manager_message!)}
                        sx={{ alignSelf: "flex-start" }}
                      >
                        {copied === i
                          ? t("numberConflict.copied")
                          : t("numberConflict.copy")}
                      </Button>
                    </>
                  )}
                </Box>
              ))}
            </Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={isSaving}>
          {paperIsRight ? t("common.close") : t("common.cancel")}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
