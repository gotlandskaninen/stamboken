import { cache } from "react";

/**
 * Per-request dedup helper.
 *
 * Uses React's `cache()` to create a per-render-pass memoized function.
 * Within a single React server render, repeated calls with the same slug
 * return the same Promise, ensuring the loader is invoked only once.
 *
 * Own module (no Payload imports) so vitest can resolve it without @payload-config.
 */
export function dedupePerRequest<T>(loader: (slug: string) => Promise<T>) {
  // React's cache() memos synchronously — we need in-flight promise dedup
  // for concurrent async callers (e.g. generateMetadata + page body).
  // Use a per-wrapped-function Map to hold in-flight promises.
  const inflight = new Map<string, Promise<T>>();

  const wrapped = cache(async (slug: string): Promise<T> => {
    const existing = inflight.get(slug);
    if (existing) return existing;

    const promise = loader(slug).finally(() => inflight.delete(slug));
    inflight.set(slug, promise);
    return promise;
  });

  return wrapped;
}
