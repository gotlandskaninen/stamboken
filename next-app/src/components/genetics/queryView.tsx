import React from "react";
import { Alert } from "@mui/material";
import { accessDeniedAt, useAccessDenials } from "@/redux/api/geneticsAccess";

interface GeneticsQuery<T> {
  currentData?: T;
  isFetching: boolean;
  error?: unknown;
  originalArgs?: unknown;
  fulfilledTimeStamp?: number;
}

/**
 * What a genetics panel shows for one query. Only the selected genebank's own
 * data (`currentData`; `data` still holds the previous genebank's after a
 * switch); nothing older than the last 401 (session) or 403 (this genebank in
 * this mode, from any genetics endpoint) until a newer success; and cached
 * data after any other failed refetch.
 */
export function useQueryView<T>({
  currentData,
  isFetching,
  error,
  originalArgs,
  fulfilledTimeStamp,
}: GeneticsQuery<T>) {
  useAccessDenials(); // a denial answered to another panel hides this one's rows too
  const status =
    error != null && typeof error === "object" && "status" in error
      ? (error as { status: unknown }).status
      : undefined;
  const confirmed = fulfilledTimeStamp ?? 0;
  const denied = accessDeniedAt(originalArgs);
  const signedOut =
    status === 401 ||
    (denied.session !== undefined && confirmed <= denied.session);
  const forbidden =
    status === 403 ||
    (denied.genebank !== undefined && confirmed <= denied.genebank);
  const data = signedOut || forbidden ? undefined : currentData;
  return {
    data,
    loading: data === undefined && isFetching,
    // Signed out: no error, the session-expired flow takes over.
    failed: !signedOut && data === undefined && (error != null || forbidden),
    stale: error != null && data !== undefined,
  };
}

export const StaleNote = () => (
  <Alert severity="warning" sx={{ mb: 2 }}>
    Kunde inte uppdatera. Visar det senast hämtade.
  </Alert>
);
