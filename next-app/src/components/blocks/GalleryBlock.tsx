"use client";

import { useRef, useState } from "react";
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

const arrowSx = {
  position: "absolute",
  top: "50%",
  transform: "translateY(-50%)",
  width: 44,
  height: 44,
  p: 0,
  border: 0,
  borderRadius: "50%",
  bgcolor: "rgba(31,27,22,0.55)",
  color: "paper.main",
  fontSize: "22px",
  lineHeight: 1,
  cursor: "pointer",
  "&:hover": { bgcolor: "rgba(31,27,22,0.8)" },
  "&:focus-visible": { outline: "2px solid var(--sb-paper)", outlineOffset: 2 },
} as const;

// One large image with arrows and swipe to step through, and a row of
// thumbnails so a visitor sees at a glance how many photos there are.
export function GalleryBlockComponent({ images }: Props) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const touchX = useRef<number | null>(null);

  const shown = (images ?? []).filter((item) => item.image?.url);
  if (shown.length === 0) return null;

  const index = Math.min(selectedIndex, shown.length - 1);
  const current = shown[index];
  const step = (d: number) =>
    setSelectedIndex((index + d + shown.length) % shown.length);
  const src = (item: GalleryImage) =>
    item.image!.sizes?.card?.url || item.image!.url;

  return (
    <Box className="gallery" sx={{ my: 8 }}>
      <Box component="figure" sx={{ m: 0 }}>
        <Box
          sx={{ position: "relative" }}
          onTouchStart={(e) => {
            touchX.current = e.touches[0].clientX;
          }}
          onTouchEnd={(e) => {
            if (touchX.current === null) return;
            const dx = e.changedTouches[0].clientX - touchX.current;
            touchX.current = null;
            if (Math.abs(dx) > 40) step(dx < 0 ? 1 : -1);
          }}
        >
          <Box
            component="img"
            src={src(current)}
            alt={current.image!.alt || current.caption || ""}
            sx={{ ...imageSx, borderRadius: "8px" }}
          />
          {shown.length > 1 && (
            <>
              <Box
                component="button"
                type="button"
                aria-label="Föregående bild"
                onClick={() => step(-1)}
                sx={{ ...arrowSx, left: 8 }}
              >
                <span aria-hidden="true">&lsaquo;</span>
              </Box>
              <Box
                component="button"
                type="button"
                aria-label="Nästa bild"
                onClick={() => step(1)}
                sx={{ ...arrowSx, right: 8 }}
              >
                <span aria-hidden="true">&rsaquo;</span>
              </Box>
            </>
          )}
        </Box>
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
            {index + 1} / {shown.length}
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
            // Up to eight share one row; fewer than six keep the six-column size.
            sm: `repeat(${Math.max(6, Math.min(shown.length, 8))}, minmax(0, 1fr))`,
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
