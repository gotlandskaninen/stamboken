import { useSyncExternalStore } from "react";

// Flask checks the same genebank access for every genetics endpoint, so a 403
// from any of them disowns all of that genebank's genetics data in that mode,
// and a 401 disowns everything this session fetched. Only answers newer than
// the denial are shown again (useQueryView), whichever panel asked.
const genebankDeniedAt = new Map<string, number>();
let sessionDeniedAt: number | undefined;
let version = 0;
const listeners = new Set<() => void>();

const genebankKey = (arg: unknown) => {
  const { mode, genebankId } = (arg ?? {}) as {
    mode?: unknown;
    genebankId?: unknown;
  };
  return `${mode}:${genebankId}`;
};

/** When the session (401) and the argument's genebank in its mode (403) were last denied. */
export const accessDeniedAt = (arg: unknown) => ({
  session: sessionDeniedAt,
  genebank: genebankDeniedAt.get(genebankKey(arg)),
});

/** onQueryStarted for the genetics endpoints: remembers a 401 or 403. */
export async function rememberAccessDenial(
  arg: unknown,
  { queryFulfilled }: { queryFulfilled: Promise<unknown> },
) {
  try {
    await queryFulfilled;
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
