import React from "react";
import { Alert } from "@mui/material";

interface GeneticsQuery<T> {
  currentData?: T;
  isFetching: boolean;
  error?: unknown;
}

/**
 * What a genetics panel shows for one query. Only the selected genebank's own
 * data (`currentData`; `data` still holds the previous genebank's after a
 * switch), never after a 401 or 403, and cached data after any other failed
 * refetch.
 */
export function queryView<T>({
  currentData,
  isFetching,
  error,
}: GeneticsQuery<T>) {
  const status =
    error != null && typeof error === "object" && "status" in error
      ? (error as { status: unknown }).status
      : undefined;
  const data = status === 401 || status === 403 ? undefined : currentData;
  return {
    data,
    loading: data === undefined && isFetching,
    // A 401 shows no error: the session-expired flow takes over.
    failed: error != null && status !== 401 && data === undefined,
    stale: error != null && data !== undefined,
  };
}

export const StaleNote = () => (
  <Alert severity="warning" sx={{ mb: 2 }}>
    Kunde inte uppdatera. Visar det senast hämtade.
  </Alert>
);
