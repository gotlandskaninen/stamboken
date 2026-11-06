// @vitest-environment node
/**
 * Pages and the public navigation cache their populated Media (url, alt,
 * focal point) in unstable_cache. Replacing a file makes Payload delete the old
 * one, so a Media change or deletion must expire the cache entries of
 * getNavigation and getPublishedPage right away, otherwise the public site
 * keeps serving a 404 image URL.
 */
import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";

const h = vi.hoisted(() => ({
  entries: [] as { tags: string[] }[],
  revalidateTag: vi.fn(),
}));

vi.mock("next/cache", () => ({
  unstable_cache: (
    fn: () => unknown,
    _keys: string[],
    opts?: { tags?: string[] },
  ) => {
    h.entries.push({ tags: opts?.tags ?? [] });
    return fn;
  },
  revalidateTag: h.revalidateTag,
  revalidatePath: vi.fn(),
}));
vi.mock("@payload-config", () => ({ default: {} }));
vi.mock("payload", () => ({
  getPayload: async () => ({
    find: async () => ({
      docs: [
        {
          id: 7,
          slug: "om-oss",
          featuredImage: { id: 3, url: "/cms-api/media/file/old.jpg" },
        },
      ],
    }),
  }),
}));

import { getPublishedPage } from "@/lib/payload-queries";
import { Media } from "@/collections/Media";

const media = { id: 3, url: "/cms-api/media/file/new.jpg", alt: "Ny" };
const changeArgs = { doc: media, previousDoc: media, operation: "update" };
const deleteArgs = { doc: media, id: 3 };

describe("Media changes revalidate cached CMS reads", () => {
  beforeAll(async () => {
    // getNavigation registers its cache entry at import, the page entry per call.
    await getPublishedPage("om-oss");
  });
  beforeEach(() => {
    h.revalidateTag.mockReset();
  });

  it("registers a navigation cache and a page cache", () => {
    const tags = h.entries.flatMap((e) => e.tags);
    expect(tags).toContain("navigation");
    expect(tags).toContain("page-om-oss");
  });

  it.each([
    ["afterChange", () => Media.hooks?.afterChange ?? [], changeArgs],
    ["afterDelete", () => Media.hooks?.afterDelete ?? [], deleteArgs],
  ])(
    "%s expires the navigation and page caches immediately",
    async (_n, hooks, args) => {
      expect(hooks().length).toBeGreaterThan(0);
      for (const hook of hooks()) await (hook as (a: unknown) => unknown)(args);

      // "default" is stale-while-revalidate: the first read after the change
      // would still get the deleted file's url, so the profile must be expire 0.
      const calls = h.revalidateTag.mock.calls;
      for (const entry of h.entries) {
        const hit = calls.filter(([tag]) => entry.tags.includes(tag));
        expect(
          hit.length > 0 && hit.every(([, profile]) => profile?.expire === 0),
          `cache entry tagged ${JSON.stringify(entry.tags)} is not expired immediately; revalidateTag calls=${JSON.stringify(calls)}`,
        ).toBe(true);
      }
    },
  );

  it.each([
    ["afterChange", () => Media.hooks?.afterChange ?? [], changeArgs],
    ["afterDelete", () => Media.hooks?.afterDelete ?? [], deleteArgs],
  ])(
    "%s survives revalidateTag throwing during render",
    async (_n, hooks, args) => {
      h.revalidateTag.mockImplementation(() => {
        throw new Error("revalidateTag during render");
      });
      for (const hook of hooks()) {
        expect(await (hook as (a: unknown) => unknown)(args)).toBe(media);
      }
    },
  );
});
