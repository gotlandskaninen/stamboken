import { notFound } from "next/navigation";
import { headers as nextHeaders } from "next/headers";
import { getPayload } from "payload";
import config from "@payload-config";
import { Container, Typography, Box, Alert } from "@mui/material";
import { RenderBlocks } from "@/components/blocks/RenderBlocks";

type Props = {
  params: Promise<{ slug: string }>;
};

export const dynamic = "force-dynamic";

export default async function PreviewPage({ params }: Props) {
  const { slug } = await params;
  const payload = await getPayload({ config });

  // Only authenticated editors/admins may view drafts. The flask-session
  // strategy resolves the user from the request's session cookie.
  const { user } = await payload.auth({ headers: await nextHeaders() });
  if (!user) notFound();

  const { docs } = await payload.find({
    collection: "pages",
    where: { slug: { equals: slug } },
    draft: true,
    limit: 1,
    overrideAccess: false,
    user,
  });

  const page = docs[0];
  if (!page) notFound();

  const pageAny = page as Record<string, any>;
  const hasBlocks =
    pageAny.layout &&
    Array.isArray(pageAny.layout) &&
    pageAny.layout.length > 0;

  return (
    <>
      <Container maxWidth="md" sx={{ pt: 3 }}>
        <Alert severity="warning" sx={{ mb: 3 }}>
          Förhandsgranskning – denna sida är inte publicerad
        </Alert>
      </Container>

      {/* Hero banner */}
      {page.featuredImage &&
        typeof page.featuredImage === "object" &&
        page.featuredImage.url && (
          <Box
            sx={{
              position: "relative",
              width: "100%",
              height: { xs: 240, sm: 300, md: 360 },
              overflow: "hidden",
            }}
          >
            <Box
              component="img"
              // Largest element above the fold: fetch it ahead of fonts/scripts.
              fetchPriority="high"
              src={page.featuredImage.url}
              alt={page.featuredImage.alt || ""}
              sx={{
                width: "100%",
                height: "100%",
                objectFit: "cover",
                // Crop around the focal point set in /admin (defaults to centre).
                objectPosition: `${page.featuredImage.focalX ?? 50}% ${page.featuredImage.focalY ?? 50}%`,
              }}
            />
            <Box
              sx={{
                position: "absolute",
                bottom: 0,
                left: 0,
                right: 0,
                background: "linear-gradient(transparent, rgba(0,0,0,0.6))",
                py: 3,
                px: { xs: 3, md: 6 },
              }}
            >
              <Container maxWidth="md">
                <Typography
                  variant="h3"
                  component="h1"
                  sx={{ color: "#fff", fontWeight: 600 }}
                >
                  {page.title}
                </Typography>
              </Container>
            </Box>
          </Box>
        )}

      {/* Title without image */}
      {!(
        page.featuredImage &&
        typeof page.featuredImage === "object" &&
        page.featuredImage.url
      ) && (
        <Container maxWidth="md" sx={{ pt: 4 }}>
          <Typography
            variant="h3"
            component="h1"
            gutterBottom
            sx={{ fontWeight: 600, mb: 3 }}
          >
            {page.title}
          </Typography>
        </Container>
      )}

      {/* Block layout */}
      {/* Same side padding as the published page gives its blocks. */}
      {hasBlocks && (
        <Box sx={{ px: { xs: 6, md: 14 }, py: { xs: 10, md: 16 } }}>
          <RenderBlocks blocks={pageAny.layout} />
        </Box>
      )}
    </>
  );
}
