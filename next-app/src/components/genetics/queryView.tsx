import React from "react";
import { Alert } from "@mui/material";
import {
  accessDeniedAt,
  dataRequestedAt,
  useAccessDenials,
} from "@/redux/api/geneticsAccess";

interface GeneticsQuery<T> {
  currentData?: T;
  isFetching: boolean;
  error?: unknown;
  status?: string;
  startedTimeStamp?: number;
  endpointName?: string;
  originalArgs?: unknown;
}

/**
 * What a genetics panel shows for one query. Only the selected genebank's own
 * data (`currentData`; `data` still holds the previous genebank's after a
 * switch); nothing asked for before the last 401 (session) or 403 (this
 * genebank in this mode, from any genetics endpoint) until a success asked for
 * after it; and cached data after any other failed refetch.
 */
export function useQueryView<T>(query: GeneticsQuery<T>) {
  const { currentData, isFetching, error, originalArgs } = query;
  useAccessDenials(); // a denial answered to another panel hides this one's rows too
  const status =
    error != null && typeof error === "object" && "status" in error
      ? (error as { status: unknown }).status
      : undefined;
  const confirmed = dataRequestedAt(query) ?? 0;
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
    denied: forbidden && !signedOut, // this genebank's genetics, in this mode
    stale: error != null && data !== undefined,
  };
}

export const StaleNote = () => (
  <Alert severity="warning" sx={{ mb: 2 }}>
    Kunde inte uppdatera. Visar det senast hämtade.
  </Alert>
);
