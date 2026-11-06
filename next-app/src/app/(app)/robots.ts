import type { MetadataRoute } from "next";

export default function robots(): MetadataRoute.Robots {
  const baseUrl =
    process.env.NEXT_PUBLIC_SITE_URL || "https://gotlandskaninen.se";
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        disallow: ["/admin", "/cms-api", "/stamboken"],
      },
    ],
    sitemap: `${baseUrl}/sitemap.xml`,
  };
}
