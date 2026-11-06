import { cache } from "react";
import { unstable_cache } from "next/cache";
import { getPayload } from "payload";
import config from "@payload-config";

export { dedupePerRequest } from "./dedupePerRequest";

type NavNode = {
  label: string;
  href: string;
  children?: {
    label: string;
    href: string;
    subtitle?: string;
    image?: string;
  }[];
};

function hrefOf(doc: any): string {
  if (doc.page && typeof doc.page === "object" && doc.page.slug)
    return `/${doc.page.slug}`;
  if (doc.externalUrl) return doc.externalUrl;
  return "#";
}

export const getNavigation = unstable_cache(
  async (): Promise<NavNode[]> => {
    try {
      const payload = await getPayload({ config });
      const { docs } = await payload.find({
        collection: "navigation",
        where: { hidden: { equals: false } },
        sort: "order",
        limit: 100,
        depth: 1, // populate page (for slug) and image (for url)
      });
      const topLevel = docs.filter((d: any) => !d.parent);
      return topLevel.map((d: any) => {
        const childDocs = docs.filter((c: any) => {
          const parentId =
            c.parent && typeof c.parent === "object" ? c.parent.id : c.parent;
          return parentId === d.id;
        });
        const node: NavNode = { label: d.label, href: hrefOf(d) };
        if (childDocs.length) {
          node.children = childDocs.map((c: any) => ({
            label: c.label,
            href: hrefOf(c),
            subtitle: c.subtitle || undefined,
            image:
              c.image && typeof c.image === "object" ? c.image.url : undefined,
          }));
        }
        return node;
      });
    } catch {
      // CMS DB unreachable — return empty so PublicNav uses FALLBACK_NAV_LINKS
      // instead of throwing and taking down the whole public layout.
      return [];
    }
  },
  ["navigation"],
  { tags: ["navigation"] },
);

const loadPublishedPage = cache(async (slug: string) => {
  const cached = unstable_cache(
    async () => {
      const payload = await getPayload({ config });
      const { docs } = await payload.find({
        collection: "pages",
        where: { slug: { equals: slug }, _status: { equals: "published" } },
        limit: 1,
      });
      return docs[0] || null;
    },
    ["published-page", slug],
    { tags: [`page-${slug}`, "pages"] },
  );
  return cached();
});

export async function getPublishedPage(slug: string) {
  return loadPublishedPage(slug);
}

export async function getAllPublishedSlugs(): Promise<string[]> {
  try {
    const payload = await getPayload({ config });
    const { docs } = await payload.find({
      collection: "pages",
      where: { _status: { equals: "published" } },
      limit: 100,
    });
    return docs.map((doc: any) => doc.slug);
  } catch {
    // Build-time: CMS database may not be available
    return [];
  }
}
