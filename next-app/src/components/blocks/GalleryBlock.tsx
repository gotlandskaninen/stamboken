"use client";

import { useCallback, useEffect, useState } from "react";
import useEmblaCarousel from "embla-carousel-react";
import { Box, IconButton, Typography } from "@mui/material";
import ChevronLeftIcon from "@mui/icons-material/ChevronLeft";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";

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

export function GalleryBlockComponent({ images }: Props) {
  const [emblaRef, emblaApi] = useEmblaCarousel({ loop: true });
  const [selectedIndex, setSelectedIndex] = useState(0);

  const onSelect = useCallback(() => {
    if (!emblaApi) return;
    setSelectedIndex(emblaApi.selectedScrollSnap());
  }, [emblaApi]);

  useEffect(() => {
    if (!emblaApi) return;
    onSelect();
    emblaApi.on("select", onSelect);
    return () => {
      emblaApi.off("select", onSelect);
    };
  }, [emblaApi, onSelect]);

  const scrollPrev = useCallback(() => emblaApi?.scrollPrev(), [emblaApi]);
  const scrollNext = useCallback(() => emblaApi?.scrollNext(), [emblaApi]);
  const scrollTo = useCallback(
    (index: number) => emblaApi?.scrollTo(index),
    [emblaApi],
  );

  if (!images || images.length === 0) return null;

  return (
    <Box sx={{ my: 4 }}>
      {/* Carousel viewport */}
      <Box sx={{ position: "relative" }}>
        <Box ref={emblaRef} sx={{ overflow: "hidden", borderRadius: 2 }}>
          <Box sx={{ display: "flex" }}>
            {images.map((item, i) => (
              <Box
                key={i}
                sx={{ flex: "0 0 100%", minWidth: 0, position: "relative" }}
              >
                {item.image?.url && (
                  <Box
                    component="img"
                    src={item.image.sizes?.card?.url || item.image.url}
                    alt={item.image.alt || item.caption || ""}
                    loading="lazy"
                    sx={{
                      width: "100%",
                      height: "auto",
                      display: "block",
                    }}
                  />
                )}
              </Box>
            ))}
          </Box>
        </Box>

        {/* Prev/Next buttons */}
        <IconButton
          onClick={scrollPrev}
          aria-label="Föregående bild"
          sx={{
            position: "absolute",
            left: 8,
            top: "50%",
            transform: "translateY(-50%)",
            bgcolor: "rgba(0,0,0,0.5)",
            color: "#fff",
            "&:hover": { bgcolor: "rgba(0,0,0,0.7)" },
            width: 40,
            height: 40,
          }}
        >
          <ChevronLeftIcon />
        </IconButton>
        <IconButton
          onClick={scrollNext}
          aria-label="Nästa bild"
          sx={{
            position: "absolute",
            right: 8,
            top: "50%",
            transform: "translateY(-50%)",
            bgcolor: "rgba(0,0,0,0.5)",
            color: "#fff",
            "&:hover": { bgcolor: "rgba(0,0,0,0.7)" },
            width: 40,
            height: 40,
          }}
        >
          <ChevronRightIcon />
        </IconButton>
      </Box>

      {/* Caption for current slide */}
      {images[selectedIndex]?.caption && (
        <Typography
          variant="caption"
          sx={{
            color: "text.secondary",
            display: "block",
            textAlign: "center",
            mt: 1,
          }}
        >
          {images[selectedIndex].caption}
        </Typography>
      )}

      {/* Dot indicators */}
      <Box
        sx={{
          display: "flex",
          justifyContent: "center",
          gap: 1,
          pt: 1.5,
        }}
      >
        {images.map((_, i) => (
          <Box
            key={i}
            onClick={() => scrollTo(i)}
            sx={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              bgcolor: i === selectedIndex ? "primary.main" : "grey.300",
              cursor: "pointer",
              transition: "background-color 0.2s",
            }}
          />
        ))}
      </Box>
    </Box>
  );
}
