"use client";

import { useState } from "react";
import { Box, Typography } from "@mui/material";

interface GalleryImage {
  image: {
    url: string;
    alt?: string;
    sizes?: { card?: { url?: string } };
  } | null;
  caption?: string;
}

interface Props {
  images: GalleryImage[];
}

const imageSx = {
  display: "block",
  width: "100%",
  aspectRatio: "3 / 2",
  objectFit: "cover",
  bgcolor: "paper.3",
} as const;

// One large image with a row of thumbnails to pick from, so a visitor sees at
// a glance how many photos there are.
export function GalleryBlockComponent({ images }: Props) {
  const [selectedIndex, setSelectedIndex] = useState(0);

  const shown = (images ?? []).filter((item) => item.image?.url);
  if (shown.length === 0) return null;

  const current = shown[Math.min(selectedIndex, shown.length - 1)];
  const src = (item: GalleryImage) =>
    item.image!.sizes?.card?.url || item.image!.url;

  return (
    <Box className="gallery" sx={{ my: 8 }}>
      <Box component="figure" sx={{ m: 0 }}>
        <Box
          component="img"
          src={src(current)}
          alt={current.image!.alt || current.caption || ""}
          sx={{ ...imageSx, borderRadius: "8px" }}
        />
        <Box
          component="figcaption"
          sx={{
            mt: 2.5,
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            gap: 4,
            fontSize: "14px",
            lineHeight: 1.4,
            color: "ink.2",
          }}
        >
          <span>{current.caption}</span>
          <Typography
            variant="mono"
            component="span"
            sx={{ whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums" }}
          >
            {shown.indexOf(current) + 1} / {shown.length}
          </Typography>
        </Box>
      </Box>

      <Box
        role="group"
        aria-label="Välj bild"
        sx={{
          mt: 3.5,
          display: "grid",
          gridTemplateColumns: {
            xs: "repeat(4, minmax(0, 1fr))",
            sm: "repeat(6, minmax(0, 1fr))",
          },
          gap: 2.5,
        }}
      >
        {shown.map((item, i) => (
          <Box
            component="button"
            key={i}
            type="button"
            aria-label={`Visa bild ${i + 1}${item.caption ? `: ${item.caption}` : ""}`}
            aria-current={item === current ? "true" : undefined}
            onClick={() => setSelectedIndex(i)}
            sx={{
              p: 0,
              border: 0,
              bgcolor: "transparent",
              borderRadius: "6px",
              cursor: "pointer",
              opacity: 0.7,
              outline: "2px solid transparent",
              outlineOffset: "2px",
              transition:
                "opacity 200ms cubic-bezier(0.2, 0.7, 0.2, 1), outline-color 200ms cubic-bezier(0.2, 0.7, 0.2, 1)",
              "&:hover": { opacity: 1 },
              '&[aria-current="true"], &:focus-visible': {
                opacity: 1,
                outlineColor: "var(--sb-skog)",
              },
            }}
          >
            <Box
              component="img"
              src={src(item)}
              alt=""
              loading="lazy"
              sx={{ ...imageSx, borderRadius: "6px" }}
            />
          </Box>
        ))}
      </Box>
    </Box>
  );
}
