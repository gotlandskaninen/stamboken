"use client";

import { useEffect, useRef, useState, useTransition } from "react";
import { Alert, Box, Button, Typography } from "@mui/material";
import { eraseBuyer, type EraseResult } from "./actions";

/**
 * The token from the link's fragment (#…). A browser never sends a fragment to
 * a server, so no access log, server log or referrer can hold it, as a query
 * string would be by nginx before this page could hide it. The address bar and
 * the history lose it at once; it lives on only in this page's memory.
 */
export function takeToken(location: Location, history: History) {
  const token = location.hash.slice(1);
  if (token) history.replaceState(null, "", location.pathname);
  return token || null;
}

const DONE: Record<Exclude<EraseResult, "error">, string> = {
  removed: "Dina uppgifter är borttagna.",
  already_removed: "Dina uppgifter är redan borttagna.",
  invalid:
    "Länken gäller inte längre. Skriv till dataskydd@gotlandskaninen.se.",
};

/** Erases only on the button (a POST): a link preview that opens the page erases nothing. */
export function EraseBuyer() {
  const token = useRef<string | null>(null);
  const [result, setResult] = useState<EraseResult | null>(null);
  const [pending, startTransition] = useTransition();

  useEffect(() => {
    token.current = takeToken(window.location, window.history);
  }, []);

  if (result && result !== "error") {
    return (
      <Alert severity={result === "invalid" ? "warning" : "success"}>
        {DONE[result]}
      </Alert>
    );
  }
  return (
    <Box
      sx={{
        display: "flex",
        flexDirection: "column",
        alignItems: "flex-start",
        gap: 2,
      }}
    >
      <Typography>
        Vi tar bort ditt namn, din ort och dina kontaktuppgifter. Det går inte
        att ångra.
      </Typography>
      {result === "error" && (
        <Alert severity="error">Något gick fel. Försök igen om en stund.</Alert>
      )}
      <Button
        variant="contained"
        disabled={pending}
        onClick={() =>
          startTransition(async () => {
            const found = token.current;
            setResult(found ? await eraseBuyer(found) : "invalid");
          })
        }
      >
        Ta bort mina uppgifter
      </Button>
    </Box>
  );
}
