import { notFound } from "next/navigation";
import { getPublishedPage } from "@/lib/payload-queries";
import { Box } from "@mui/material";
import { RenderBlocks } from "@/components/blocks/RenderBlocks";
import { PageHeader } from "@/components/public/PageHeader";
import { MembershipSteps } from "@/components/public/MembershipSteps";
import { NextSteps, hasNextSteps } from "@/components/public/NextSteps";
import { TEXT_MAX_WIDTH, TEXT_ROW, WIDE } from "@/components/blocks/textColumn";
import type { Metadata } from "next";

const BREADCRUMB_PARENTS: Record<string, { label: string; href: string }> = {
  "rasram-gotlandskanin": { label: "Gotlandskanin", href: "/gotlandskanin" },
  "rasram-mellerudskanin": { label: "Mellerudskanin", href: "/mellerudskanin" },
};

// The membership page exists to get an application: the button sits under
// the lede, and the three steps of /ansok follow the CMS text, so how to join
// is written in one place.
const JOIN_SLUG = "bli-medlem";
const JOIN_ACTION = { label: "Ansök om medlemskap", href: "/ansok" };

type Props = { params: Promise<{ slug: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { slug } = await params;
  const page = await getPublishedPage(slug);
  if (!page) return {};
  const title = page.meta?.title || page.title;
  return {
    // The layout's title template ends with the association's name, so the
    // page about the association would otherwise repeat it.
    title:
      title === "Föreningen Gotlandskaninen"
        ? {
            absolute:
              "Föreningen Gotlandskaninen – bevarande av svenska lantraskaniner",
          }
        : title,
    description: page.meta?.description || undefined,
    openGraph: {
      title: page.meta?.title || page.title,
      description: page.meta?.description || undefined,
      ...(page.featuredImage &&
      typeof page.featuredImage === "object" &&
      page.featuredImage.url
        ? { images: [{ url: page.featuredImage.url }] }
        : {}),
    },
  };
}

export default async function CmsPage({ params }: Props) {
  const { slug } = await params;
  const page = await getPublishedPage(slug);
  if (!page) notFound();

  const hasImage =
    page.featuredImage &&
    typeof page.featuredImage === "object" &&
    page.featuredImage.url;

  // The Pages collection has a `layout` blocks field, but generated types
  // may lag behind the schema. Cast to access it safely.
  const pageAny = page as Record<string, any>;
  const hasBlocks =
    pageAny.layout &&
    Array.isArray(pageAny.layout) &&
    pageAny.layout.length > 0;

  return (
    <>
      <PageHeader
        section={page.title}
        title={page.title}
        lede={pageAny.subtitle || undefined}
        parent={
          Object.hasOwn(BREADCRUMB_PARENTS, slug)
            ? BREADCRUMB_PARENTS[slug]
            : undefined
        }
        action={slug === JOIN_SLUG ? JOIN_ACTION : undefined}
        image={
          hasImage
            ? {
                src: (page.featuredImage as any).url,
                alt: (page.featuredImage as any).alt || "",
                // Crop around the focal point set in /admin (defaults to centre).
                position: `${(page.featuredImage as any).focalX ?? 50}% ${(page.featuredImage as any).focalY ?? 50}%`,
                caption: (page.featuredImage as any).caption || undefined,
              }
            : undefined
        }
      />

      {/* The membership steps show even if the CMS page has no text yet. */}
      {(hasBlocks || slug === JOIN_SLUG) && (
        <Box
          sx={{
            px: { xs: 6, md: 14 },
            py: { xs: 10, md: 16 },
            // Wide screens: the next step follows the reader in a side
            // column instead of waiting after the last paragraph.
            ...(hasNextSteps(slug) && {
              [WIDE]: {
                display: "grid",
                gridTemplateColumns: `minmax(0, ${TEXT_MAX_WIDTH}px) 296px`,
                columnGap: 14,
                alignItems: "start",
              },
            }),
          }}
        >
          <Box sx={{ minWidth: 0 }}>
            {hasBlocks && <RenderBlocks blocks={pageAny.layout} />}
            {slug === JOIN_SLUG && (
              <Box sx={{ ...TEXT_ROW, maxWidth: TEXT_MAX_WIDTH }}>
                <Box sx={{ gridColumn: { md: 2 }, minWidth: 0 }}>
                  <MembershipSteps />
                </Box>
              </Box>
            )}
          </Box>
          <Box
            sx={{
              ...TEXT_ROW,
              maxWidth: TEXT_MAX_WIDTH,
              // 96px clears the sticky site header.
              [WIDE]: { display: "block", position: "sticky", top: 96 },
            }}
          >
            <Box sx={{ gridColumn: { md: 2 }, minWidth: 0 }}>
              <NextSteps slug={slug} />
            </Box>
          </Box>
        </Box>
      )}
    </>
  );
}
