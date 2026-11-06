import type { MetadataRoute } from "next";
import { getAllPublishedSlugs } from "@/lib/payload-queries";

// Force dynamic rendering so sitemap reflects CMS changes without rebuild
export const dynamic = "force-dynamic";

export default async function sitemap(): Promise<MetadataRoute.Sitemap> {
  const slugs = await getAllPublishedSlugs();
  const baseUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://gotlandskaninen.se";

  const cmsPages = slugs.map((slug: string) => ({
    url: `${baseUrl}/${slug}`,
    lastModified: new Date(),
    changeFrequency: "monthly" as const,
  }));

  return [
    { url: baseUrl, lastModified: new Date(), changeFrequency: "weekly" },
    ...cmsPages,
  ];
}
