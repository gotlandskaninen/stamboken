import { defaultSerializeQueryArgs } from "@reduxjs/toolkit/query";

// When each cached genetics entry last answered 401 or 403, by its cache key.
// Its older data stays hidden until a newer success (queryView), whichever
// component made the request and whatever error comes next.
const deniedAt = new Map<string, number>();

const entryKey = (endpointName: string | undefined, queryArgs: unknown) =>
  defaultSerializeQueryArgs({
    queryArgs,
    endpointName: endpointName ?? "",
    endpointDefinition: undefined as never, // unused by the default serializer
  });

export const accessDeniedAt = (
  endpointName: string | undefined,
  arg: unknown,
) => deniedAt.get(entryKey(endpointName, arg));

/** onQueryStarted for the cached genetics endpoints: remembers a 401 or 403. */
export async function rememberAccessDenial(
  arg: unknown,
  {
    queryFulfilled,
    getCacheEntry,
  }: {
    queryFulfilled: Promise<unknown>;
    getCacheEntry: () => { endpointName?: string };
  },
) {
  try {
    await queryFulfilled;
  } catch (rejection) {
    const status = (rejection as { error?: { status?: unknown } }).error
      ?.status;
    if (status === 401 || status === 403)
      deniedAt.set(entryKey(getCacheEntry().endpointName, arg), Date.now());
  }
}
