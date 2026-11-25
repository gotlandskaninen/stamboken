"use client";

import {
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  useMediaQuery,
} from "@mui/material";
import { FargNyckel } from "./FargNyckel";
import { useFargatlas } from "./useFargatlas";

/**
 * "Hjälp mig välja" in the colour picker: the guide in a dialog, full screen on a phone and kept at the top so the
 * answers do not move between steps. A tap beside it does not close it (that would lose the answers); Stäng and
 * Escape do, and choose nothing.
 */
export function FargNyckelDialog({
  open,
  onClose,
  onValj,
  saknas,
}: {
  open: boolean;
  onClose: () => void;
  onValj: (nummer: number, paminnelser: string[]) => void;
  saknas?: number | null;
}) {
  const data = useFargatlas(open);
  // MUI's breakpoints.down("sm"), as a plain query so the dialog works without a theme provider.
  const smal = useMediaQuery("(max-width:599.95px)");
  return (
    <Dialog
      open={open}
      onClose={(_, reason) => {
        if (reason !== "backdropClick") onClose();
      }}
      fullScreen={smal}
      fullWidth
      maxWidth="sm"
      sx={{ "& .MuiDialog-container": { alignItems: "flex-start" } }}
    >
      <DialogTitle>Hjälp mig välja</DialogTitle>
      <DialogContent>
        <FargNyckel data={data} onValj={onValj} saknas={saknas} />
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Stäng</Button>
      </DialogActions>
    </Dialog>
  );
}
