import { useSyncExternalStore } from "react";
import { defaultSerializeQueryArgs } from "@reduxjs/toolkit/query";

// Flask checks the same genebank access for every genetics endpoint, so a 403
// from any of them disowns all of that genebank's genetics data in that mode,
// and a 401 disowns everything this session fetched. Only answers to requests
// that STARTED after the denial are shown again (useQueryView), whichever
// panel asked: a request authorised before a revocation can end after it.
const genebankDeniedAt = new Map<string, number>();
let sessionDeniedAt: number | undefined;
// When the request behind each entry's cached data started, by cache key.
const dataStartedAt = new Map<string, number>();
let version = 0;
const listeners = new Set<() => void>();

const genebankKey = (arg: unknown) => {
  const { mode, genebankId } = (arg ?? {}) as {
    mode?: unknown;
    genebankId?: unknown;
  };
  return `${mode}:${genebankId}`;
};

const entryKey = (endpointName: string | undefined, queryArgs: unknown) =>
  defaultSerializeQueryArgs({
    queryArgs,
    endpointName: endpointName ?? "",
    endpointDefinition: undefined as never, // unused by the default serializer
  });

/** When the request whose answer an entry now holds started. */
export const dataRequestedAt = (entry: {
  status?: string;
  startedTimeStamp?: number;
  endpointName?: string;
  originalArgs?: unknown;
}) =>
  // Fulfilled: the data is the latest request's. Otherwise a newer request is
  // running or failed, and the data is from the success recorded below.
  entry.status === "fulfilled"
    ? entry.startedTimeStamp
    : dataStartedAt.get(entryKey(entry.endpointName, entry.originalArgs));

/** When the session (401) and the argument's genebank in its mode (403) were last denied. */
export const accessDeniedAt = (arg: unknown) => ({
  session: sessionDeniedAt,
  genebank: genebankDeniedAt.get(genebankKey(arg)),
});

/** onQueryStarted for the genetics endpoints: remembers a 401 or 403, and when a success was asked for. */
export async function rememberAccessDenial(
  arg: unknown,
  {
    queryFulfilled,
    getCacheEntry,
  }: {
    queryFulfilled: Promise<unknown>;
    getCacheEntry: () => { endpointName?: string; startedTimeStamp?: number };
  },
) {
  const { endpointName, startedTimeStamp } = getCacheEntry(); // this request's
  try {
    await queryFulfilled;
    if (startedTimeStamp !== undefined)
      dataStartedAt.set(entryKey(endpointName, arg), startedTimeStamp);
  } catch (rejection) {
    const status = (rejection as { error?: { status?: unknown } }).error
      ?.status;
    if (status === 401) sessionDeniedAt = Date.now();
    else if (status === 403) genebankDeniedAt.set(genebankKey(arg), Date.now());
    else return;
    version += 1;
    listeners.forEach((listener) => listener());
  }
}

const subscribe = (listener: () => void) => {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
};

/** Re-renders the caller when any genetics answer is denied. */
export const useAccessDenials = () =>
  useSyncExternalStore(
    subscribe,
    () => version,
    () => version,
  );
