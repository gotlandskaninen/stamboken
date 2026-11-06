"use client";

import React, { useState, useTransition } from "react";
import {
  Box,
  Typography,
  Chip,
  Button,
  Collapse,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Table,
  TableBody,
  TableCell,
  TableRow,
  Paper,
} from "@mui/material";
import {
  Undo as UndoIcon,
  Restore as RestoreIcon,
  ExpandMore as ExpandIcon,
  ExpandLess as CollapseIcon,
} from "@mui/icons-material";
import { useSnackbar } from "@/components/SnackbarProvider";
import {
  revertAuditEntry,
  restoreRecord,
} from "@/app/(app)/stamboken/(dashboard)/individ/[number]/audit-actions";
import type { AuditLogEntry } from "@/app/(app)/stamboken/(dashboard)/individ/[number]/audit-types";

interface AuditTimelineProps {
  tableName: string;
  recordId: string | number;
  entries: AuditLogEntry[];
  revalidatePath?: string;
}

const operationColors: Record<string, "success" | "warning" | "error"> = {
  INSERT: "success",
  UPDATE: "warning",
  DELETE: "error",
};

const operationLabels: Record<string, string> = {
  INSERT: "Skapad",
  UPDATE: "Ändrad",
  DELETE: "Borttagen",
};

// History imported from the old Stamboken: shown, never reverted (the API refuses too).
const isImported = (entry: AuditLogEntry) =>
  (entry.schema_name ?? "public") !== "public";

function formatDate(iso: string): string {
  return new Date(iso).toLocaleString("sv-SE");
}

function FieldChanges({ entry }: { entry: AuditLogEntry }) {
  if (entry.operation !== "UPDATE" || !entry.changed_fields) return null;

  return (
    <Table size="small">
      <TableBody>
        {entry.changed_fields.map((field) => (
          <TableRow key={field}>
            <TableCell sx={{ fontWeight: "bold", width: "30%" }}>
              {field}
            </TableCell>
            <TableCell
              sx={{ textDecoration: "line-through", color: "text.secondary" }}
            >
              {JSON.stringify(entry.old_data?.[field] ?? null)}
            </TableCell>
            <TableCell>
              {JSON.stringify(entry.new_data?.[field] ?? null)}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function AuditTimeline({
  tableName,
  recordId,
  entries,
  revalidatePath: revalidate,
}: AuditTimelineProps) {
  const [isPending, startTransition] = useTransition();
  const { showSnackbar } = useSnackbar();
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [confirmDialog, setConfirmDialog] = useState<{
    type: "revert" | "restore";
    entry: AuditLogEntry;
  } | null>(null);

  if (!entries.length) {
    return (
      <Typography
        sx={{
          color: "text.secondary",
        }}
      >
        Ingen ändringshistorik
      </Typography>
    );
  }

  const handleConfirm = () => {
    if (!confirmDialog) return;
    const { type, entry } = confirmDialog;
    startTransition(async () => {
      const result =
        type === "revert"
          ? await revertAuditEntry(entry.id, undefined, revalidate)
          : await restoreRecord(tableName, recordId, entry.id, revalidate);
      if (result.success) {
        showSnackbar(result.message, "success");
      } else {
        showSnackbar(result.error || "Något gick fel", "error");
      }
      setConfirmDialog(null);
    });
  };

  return (
    <Box>
      {entries.map((entry) => (
        <Paper key={entry.id} sx={{ p: 2, mb: 1 }} variant="outlined">
          <Box
            sx={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "center",
            }}
          >
            <Box
              sx={{
                display: "flex",
                gap: 1,
                alignItems: "center",
                cursor: entry.operation === "UPDATE" ? "pointer" : "default",
              }}
              onClick={() =>
                entry.operation === "UPDATE" &&
                setExpandedId(expandedId === entry.id ? null : entry.id)
              }
            >
              <Chip
                label={operationLabels[entry.operation] || entry.operation}
                color={operationColors[entry.operation] || "default"}
                size="small"
              />
              <Typography
                variant="body2"
                sx={{
                  color: "text.secondary",
                }}
              >
                {formatDate(entry.changed_at)}
              </Typography>
              {isImported(entry) && (
                <Chip label="Gamla Stamboken" size="small" variant="outlined" />
              )}
              {entry.changed_by && (
                <Typography
                  variant="body2"
                  sx={{
                    color: "text.secondary",
                  }}
                >
                  av {entry.changed_by}
                </Typography>
              )}
              {entry.operation === "UPDATE" &&
                (expandedId === entry.id ? (
                  <CollapseIcon fontSize="small" />
                ) : (
                  <ExpandIcon fontSize="small" />
                ))}
            </Box>
            {entry.operation === "UPDATE" && !isImported(entry) && (
              <Box sx={{ display: "flex", gap: 1 }}>
                <Button
                  size="small"
                  startIcon={<UndoIcon />}
                  onClick={() => setConfirmDialog({ type: "revert", entry })}
                  disabled={isPending}
                >
                  Ångra
                </Button>
                <Button
                  size="small"
                  startIcon={<RestoreIcon />}
                  onClick={() => setConfirmDialog({ type: "restore", entry })}
                  disabled={isPending}
                >
                  Återställ
                </Button>
              </Box>
            )}
          </Box>
          {entry.operation === "UPDATE" && (
            <Collapse in={expandedId === entry.id}>
              <Box sx={{ mt: 1 }}>
                <FieldChanges entry={entry} />
              </Box>
            </Collapse>
          )}
        </Paper>
      ))}

      <Dialog open={!!confirmDialog} onClose={() => setConfirmDialog(null)}>
        <DialogTitle>
          {confirmDialog?.type === "revert"
            ? "Ångra ändring?"
            : "Återställ till före denna ändring?"}
        </DialogTitle>
        <DialogContent>
          <Typography>
            {confirmDialog?.type === "revert"
              ? "Detta ångrar de ändrade fälten från denna specifika ändring."
              : "Detta återställer hela posten till tillståndet innan denna ändring gjordes."}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setConfirmDialog(null)}>Avbryt</Button>
          <Button
            onClick={handleConfirm}
            variant="contained"
            color="primary"
            disabled={isPending}
          >
            {isPending ? "Bearbetar..." : "Bekräfta"}
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
