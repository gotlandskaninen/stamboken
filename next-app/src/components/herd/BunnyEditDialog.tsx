"use client";

import React, { useEffect, useState, useTransition } from "react";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  MenuItem,
  TextField,
} from "@mui/material";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import ExpandLessIcon from "@mui/icons-material/ExpandLess";
import ExpandMoreIcon from "@mui/icons-material/ExpandMore";
import HistoryIcon from "@mui/icons-material/History";
import { useTranslation } from "react-i18next";
import AuditTimeline from "@/components/audit/AuditTimeline";
import type { AuditLogEntry } from "@/app/(app)/stamboken/(dashboard)/individ/[number]/audit-types";
import {
  patchBunny,
  deleteBunny,
  getAuditHistory,
  type RosterBunny,
} from "@/app/(app)/stamboken/(dashboard)/min-besattning/actions";

interface BunnyEditDialogProps {
  open: boolean;
  bunny: RosterBunny;
  onClose: () => void;
  onSaved: () => void;
  /** Called after a successful delete (instead of onSaved) so the roster can offer undo. */
  onDeleted: (bunny: RosterBunny) => void;
}

const FATES = [
  "undecided",
  "kept_unregistered",
  "sold_unregistered",
  "culled",
  "died",
] as const;

/** Edit a roster bunny's observed details before promotion (Phase 15). */
export function BunnyEditDialog({
  open,
  bunny,
  onClose,
  onSaved,
  onDeleted,
}: BunnyEditDialogProps) {
  const { t } = useTranslation();
  const [isPending, startTransition] = useTransition();

  const [label, setLabel] = useState(bunny.label || "");
  const [observedSex, setObservedSex] = useState(bunny.observed_sex || "");
  const [observedColor, setObservedColor] = useState(
    bunny.observed_color || "",
  );
  const [notes, setNotes] = useState(bunny.notes || "");
  const [fate, setFate] = useState<string>(bunny.fate);
  const [error, setError] = useState<string | null>(null);
  // Destructive action gets its own confirmation dialog — never a morphing
  // button next to Spara (confuses non-technical users about what happens).
  const [confirmOpen, setConfirmOpen] = useState(false);
  // Change history: the audit endpoint is manager-only; non-managers get an
  // empty list back and the section stays hidden — no role plumbing needed.
  const [auditEntries, setAuditEntries] = useState<AuditLogEntry[]>([]);
  const [showHistory, setShowHistory] = useState(false);

  // Re-init when the dialog is reused for another bunny
  useEffect(() => {
    setLabel(bunny.label || "");
    setObservedSex(bunny.observed_sex || "");
    setObservedColor(bunny.observed_color || "");
    setNotes(bunny.notes || "");
    setFate(bunny.fate);
    setError(null);
    setConfirmOpen(false);
    setShowHistory(false);
    setAuditEntries([]);
    getAuditHistory("bunny", bunny.id).then(setAuditEntries);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bunny.id]);

  const handleSave = () => {
    setError(null);
    startTransition(async () => {
      const result = await patchBunny(bunny.id, {
        label: label || null,
        observed_sex: observedSex || null,
        observed_color: observedColor || null,
        notes: notes || null,
        fate: fate as RosterBunny["fate"],
      });
      if (result.success) {
        onSaved();
      } else {
        setError(t("bunnyEdit.errorSave"));
      }
    });
  };

  const handleDelete = () => {
    setError(null);
    startTransition(async () => {
      const result = await deleteBunny(bunny.id);
      setConfirmOpen(false);
      if (result.success) {
        onDeleted(bunny);
      } else {
        setError(t("bunnyEdit.errorDelete"));
      }
    });
  };

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xs" fullWidth>
      <DialogTitle>
        {t("bunnyEdit.title")}
        {bunny.provisional_number ? ` — ${bunny.provisional_number}` : ""}
      </DialogTitle>
      <DialogContent>
        {/* pt gives the first field's floating label headroom — otherwise it
            clips against the DialogTitle (MUI zeroes DialogContent's top pad) */}
        <Box
          sx={{
            display: "flex",
            flexDirection: "column",
            gap: 2,
            pt: 1.5,
          }}
        >
          {error && (
            <Alert severity="error" onClose={() => setError(null)}>
              {error}
            </Alert>
          )}
          <TextField
            label={t("bunnyEdit.label")}
            size="small"
            fullWidth
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            slotProps={{
              htmlInput: { maxLength: 40 },
            }}
          />
          <TextField
            label={t("bunnyEdit.sex")}
            size="small"
            select
            fullWidth
            value={observedSex}
            onChange={(e) => setObservedSex(e.target.value)}
          >
            <MenuItem value="">{t("bunnyEdit.sexUnknown")}</MenuItem>
            <MenuItem value="female">{t("bunnyEdit.sexFemale")}</MenuItem>
            <MenuItem value="male">{t("bunnyEdit.sexMale")}</MenuItem>
          </TextField>
          <TextField
            label={t("bunnyEdit.color")}
            size="small"
            fullWidth
            value={observedColor}
            onChange={(e) => setObservedColor(e.target.value)}
            slotProps={{
              htmlInput: { maxLength: 60 },
            }}
          />
          <TextField
            label={t("bunnyEdit.notes")}
            size="small"
            fullWidth
            multiline
            minRows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
          <TextField
            label={t("bunnyEdit.fate")}
            size="small"
            select
            fullWidth
            value={fate}
            onChange={(e) => setFate(e.target.value)}
          >
            {FATES.map((f) => (
              <MenuItem key={f} value={f}>
                {t(`bunny.fate.${f}`)}
              </MenuItem>
            ))}
          </TextField>

          {/* Ändringshistorik — only rendered when the audit API returned
              entries (i.e. the user is a manager/admin) */}
          {auditEntries.length > 0 && (
            <Box>
              <Button
                size="small"
                startIcon={<HistoryIcon />}
                endIcon={showHistory ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                onClick={() => setShowHistory((v) => !v)}
              >
                {t("bunnyEdit.history")} ({auditEntries.length})
              </Button>
              <Collapse in={showHistory}>
                <Box sx={{ mt: 1 }}>
                  <AuditTimeline
                    tableName="bunny"
                    recordId={bunny.id}
                    entries={auditEntries}
                    revalidatePath="/stamboken/min-besattning"
                  />
                </Box>
              </Collapse>
            </Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2, justifyContent: "space-between" }}>
        <Button
          color="error"
          startIcon={<DeleteOutlineIcon />}
          disabled={isPending}
          onClick={() => setConfirmOpen(true)}
          sx={{ minHeight: 44 }}
        >
          {t("bunnyEdit.delete")}
        </Button>
        <Box
          sx={{
            display: "flex",
            gap: 1,
          }}
        >
          <Button
            variant="outlined"
            onClick={onClose}
            disabled={isPending}
            sx={{ minHeight: 44 }}
          >
            {t("bunnyEdit.cancel")}
          </Button>
          <Button
            variant="contained"
            onClick={handleSave}
            disabled={isPending}
            sx={{ minHeight: 44 }}
            startIcon={
              isPending ? (
                <CircularProgress size={14} color="inherit" />
              ) : undefined
            }
          >
            {isPending ? t("bunnyEdit.saving") : t("bunnyEdit.save")}
          </Button>
        </Box>
      </DialogActions>

      {/* Delete confirmation — its own dialog with exactly two choices */}
      <Dialog
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        maxWidth="xs"
        fullWidth
      >
        <DialogTitle>{t("bunnyEdit.deleteConfirmTitle")}</DialogTitle>
        <DialogContent>
          <DialogContentText>{t("bunnyEdit.deleteConfirm")}</DialogContentText>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button
            variant="outlined"
            onClick={() => setConfirmOpen(false)}
            disabled={isPending}
            sx={{ minHeight: 44 }}
          >
            {t("bunnyEdit.cancel")}
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleDelete}
            disabled={isPending}
            sx={{ minHeight: 44 }}
            startIcon={
              isPending ? (
                <CircularProgress size={14} color="inherit" />
              ) : (
                <DeleteOutlineIcon />
              )
            }
          >
            {t("bunnyEdit.deleteConfirmButton")}
          </Button>
        </DialogActions>
      </Dialog>
    </Dialog>
  );
}
