"use client";

import { Alert, Button, Box } from "@mui/material";

// A page of the dashboard that throws shows this inside the menu, not the
// framework's bare "Application error".
export default function DashboardError({ reset }: { reset: () => void }) {
  return (
    <Box sx={{ mt: 4 }}>
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={reset}>
            Försök igen
          </Button>
        }
      >
        Något gick fel. Försök igen om en stund.
      </Alert>
    </Box>
  );
}
