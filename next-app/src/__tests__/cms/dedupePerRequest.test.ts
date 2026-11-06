import { describe, it, expect, vi } from "vitest";
import { dedupePerRequest } from "@/lib/dedupePerRequest";

describe("dedupePerRequest", () => {
  it("calls the loader once for repeated calls with the same key", async () => {
    const loader = vi.fn(async (slug: string) => ({ slug }));
    const wrapped = dedupePerRequest(loader);
    const [a, b] = await Promise.all([
      wrapped("foreningen"),
      wrapped("foreningen"),
    ]);
    expect(a).toEqual({ slug: "foreningen" });
    expect(b).toEqual({ slug: "foreningen" });
    expect(loader).toHaveBeenCalledTimes(1);
  });

  it("calls the loader separately for different keys", async () => {
    const loader = vi.fn(async (slug: string) => ({ slug }));
    const wrapped = dedupePerRequest(loader);
    await wrapped("a");
    await wrapped("b");
    expect(loader).toHaveBeenCalledTimes(2);
  });
});
