import React from "react";
import { Alert, Button } from "@mui/material";

interface GeneticsErrorProps {
  error: unknown;
  onRetry: () => void;
}

/** One message per cause: no access, logged out, or the computation failed (with a retry). */
const GeneticsError = ({ error, onRetry }: GeneticsErrorProps) => {
  const status =
    error != null && typeof error === "object" && "status" in error
      ? (error as { status: unknown }).status
      : undefined;

  if (status === 403) {
    return (
      <Alert severity="error" sx={{ mb: 6 }}>
        Du har inte behörighet att se genetiken för den här genbanken.
      </Alert>
    );
  }
  if (status === 401) {
    return (
      <Alert severity="warning" sx={{ mb: 6 }}>
        Du är utloggad. Logga in igen för att se beräkningen.
      </Alert>
    );
  }
  return (
    <Alert
      severity="error"
      sx={{ mb: 6 }}
      action={
        <Button color="inherit" size="small" onClick={onRetry}>
          Försök igen
        </Button>
      }
    >
      Beräkningen gick inte att hämta. Försök igen om en stund.
    </Alert>
  );
};

export default GeneticsError;
