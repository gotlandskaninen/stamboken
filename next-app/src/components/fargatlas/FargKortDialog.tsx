"use client";

import {
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
} from "@mui/material";
import { FargKort } from "./FargKort";
import { useFargatlas } from "./useFargatlas";

/** "Visa färgen": the colour's card from the atlas, read when the dialog opens. */
export function FargKortDialog({
  id,
  open,
  onClose,
}: {
  id: number;
  open: boolean;
  onClose: () => void;
}) {
  const data = useFargatlas(open);
  const farg = data?.atlas.farger.find((f) => f.id === id);

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Färgatlas</DialogTitle>
      <DialogContent>
        {data === undefined ? (
          <CircularProgress aria-label="Hämtar färgen" />
        ) : farg ? (
          <FargKort farg={farg} fotoBas={data!.fotoBas} />
        ) : (
          <p role="alert">
            {data === null
              ? "Färgatlasen gick inte att hämta. Försök igen senare."
              : "Färgen finns inte i färgatlasen."}
          </p>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Stäng</Button>
      </DialogActions>
    </Dialog>
  );
}
