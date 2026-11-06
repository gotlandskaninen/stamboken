"use client";

import { useState } from "react";
import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  TextField,
} from "@mui/material";

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  cancelLabel = "Avbryt",
  confirmColor = "primary",
  typeToConfirm,
  busy = false,
  onConfirm,
  onClose,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  cancelLabel?: string;
  confirmColor?: "primary" | "error" | "warning";
  /** When set, confirm stays disabled until the user types this exact
   *  string (mass logout: "LOGGA UT ALLA"). */
  typeToConfirm?: string;
  /** True while the confirmed action is in flight: both buttons disable and
   *  the dialog ignores close, so a double-click cannot fire the action
   *  twice (PersonsCard runs six destructive mutations through here). */
  busy?: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const [typed, setTyped] = useState("");
  const blocked = typeToConfirm !== undefined && typed !== typeToConfirm;
  const close = () => {
    if (busy) return;
    setTyped("");
    onClose();
  };
  return (
    <Dialog open={open} onClose={close}>
      <DialogTitle>{title}</DialogTitle>
      <DialogContent>
        <DialogContentText>{body}</DialogContentText>
        {typeToConfirm !== undefined && (
          <TextField
            fullWidth
            size="small"
            sx={{ mt: 2 }}
            label={`Skriv ”${typeToConfirm}” för att bekräfta`}
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
          />
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={close} variant="outlined" disabled={busy}>
          {cancelLabel}
        </Button>
        <Button
          onClick={() => {
            setTyped("");
            onConfirm();
          }}
          variant="contained"
          color={confirmColor}
          disabled={blocked || busy}
        >
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
