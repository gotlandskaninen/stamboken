"use client";

import { Alert, Button, Box } from "@mui/material";

export default function IndividualError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <Box
      sx={{
        mt: 4,
      }}
    >
      <Alert
        severity="error"
        action={
          <Button color="inherit" size="small" onClick={reset}>
            Försök igen
          </Button>
        }
      >
        Något gick fel vid laddning av individsidan.
      </Alert>
    </Box>
  );
}
