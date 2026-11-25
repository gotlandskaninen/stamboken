import React from "react";
import { Alert } from "@mui/material";
import { accessDeniedAt } from "@/redux/api/geneticsAccess";

interface GeneticsQuery<T> {
  currentData?: T;
  isFetching: boolean;
  error?: unknown;
  endpointName?: string;
  originalArgs?: unknown;
  fulfilledTimeStamp?: number;
}

/**
 * What a genetics panel shows for one query. Only the selected genebank's own
 * data (`currentData`; `data` still holds the previous genebank's after a
 * switch), nothing that a 401 or 403 disowned until a newer success, and
 * cached data after any other failed refetch.
 */
export function queryView<T>({
  currentData,
  isFetching,
  error,
  endpointName,
  originalArgs,
  fulfilledTimeStamp,
}: GeneticsQuery<T>) {
  const status =
    error != null && typeof error === "object" && "status" in error
      ? (error as { status: unknown }).status
      : undefined;
  const deniedAt = accessDeniedAt(endpointName, originalArgs);
  const disowned =
    status === 401 ||
    status === 403 ||
    (deniedAt !== undefined && (fulfilledTimeStamp ?? 0) <= deniedAt);
  const data = disowned ? undefined : currentData;
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
