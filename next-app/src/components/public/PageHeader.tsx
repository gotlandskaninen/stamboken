import Link from "next/link";
import { Box, Typography } from "@mui/material";

interface PageHeaderImage {
  /** Path under /public, e.g. "/stamboken/hero-kustvandring.jpg". */
  src: string;
  alt: string;
  /** CSS object-position for the cover crop; defaults to centre. */
  position?: string;
  /** Visible caption under the lede, e.g. which breed the photo shows. */
  caption?: string;
}

interface PageHeaderProps {
  section: string;
  title: string;
  lede?: string;
  /** Optional photo behind the header — same look as the CMS pages' hero. */
  image?: PageHeaderImage;
}

export function PageHeader({ section, title, lede, image }: PageHeaderProps) {
  return (
    <Box
      component="header"
      sx={{
        position: "relative",
        overflow: "hidden",
        bgcolor: "skog.main",
        color: "paper.main",
        ...(image && {
          display: "flex",
          flexDirection: "column",
          justifyContent: "flex-end",
          minHeight: { md: 360 },
        }),
      }}
    >
      {image && (
        // Phones: the photo is a 16:9 banner above the text (a cover crop of
        // a landscape photo behind stacked copy left only a sliver visible).
        // From md it is the backdrop behind the text, as on the CMS pages.
        <Box
          sx={{
            position: { xs: "relative", md: "absolute" },
            inset: { md: 0 },
            aspectRatio: { xs: "16 / 9", md: "auto" },
          }}
        >
          <Box
            component="img"
            fetchPriority="high"
            src={image.src}
            alt={image.alt}
            sx={{
              position: "absolute",
              inset: 0,
              width: "100%",
              height: "100%",
              objectFit: "cover",
              objectPosition: image.position ?? "50% 50%",
            }}
          />
          <Box
            aria-hidden
            sx={{
              position: "absolute",
              inset: 0,
              background: {
                xs: "linear-gradient(180deg, rgba(31,51,34,0) 75%, rgba(31,51,34,0.85) 100%)",
                // Dark all the way up: the breadcrumb sits a third down and needs 4.5:1.
                md: "linear-gradient(180deg, rgba(31,27,22,0.7) 0%, rgba(31,27,22,0.58) 45%, rgba(31,27,22,0.8) 100%)",
              },
            }}
          />
        </Box>
      )}
      <Box
        sx={{
          position: "relative",
          py: { xs: image ? 8 : 12, md: 14 },
          px: { xs: 6, md: 14 },
        }}
      >
        <Typography
          variant="mono"
          sx={{
            // Full strength: the "Hem" link must keep 4.5:1 over a bright photo.
            color: "paper.main",
            mb: 4.5,
            display: "block",
          }}
        >
          <Link href="/" style={{ color: "inherit", textDecoration: "none" }}>
            Hem
          </Link>
          {" / "}
          <Box component="strong" sx={{ color: "paper.main" }}>
            {section}
          </Box>
        </Typography>
        <Typography
          variant="h1"
          component="h1"
          sx={{
            color: "paper.main",
            fontSize: { xs: "40px", md: "clamp(40px, 6.4vw, 80px)" },
            lineHeight: 1,
            letterSpacing: "-0.025em",
            m: 0,
          }}
        >
          {title}
        </Typography>
        {lede && (
          <Typography
            variant="lede"
            sx={{
              mt: 4.5,
              color: "rgba(244,241,234,0.85)",
              maxWidth: 720,
              display: "block",
            }}
          >
            {lede}
          </Typography>
        )}
        {image?.caption && (
          <Typography
            variant="mono"
            component="p"
            sx={{ mt: 6, mb: 0, color: "rgba(244,241,234,0.75)" }}
          >
            Bild: {image.caption}
          </Typography>
        )}
      </Box>
    </Box>
  );
}
