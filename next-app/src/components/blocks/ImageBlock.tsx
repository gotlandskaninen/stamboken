import { Box, Typography } from "@mui/material";

interface ImageSize {
  url?: string;
}

interface Props {
  image: {
    url: string;
    alt?: string;
    sizes?: { thumbnail?: ImageSize; card?: ImageSize };
  } | null;
  caption?: string;
  size?: "small" | "medium" | "full";
}

const maxWidthMap = {
  small: 400,
  medium: 600,
  full: "100%",
};

// Prefer a generated rendition over the original: thumbnail for small blocks,
// card otherwise, falling back to the original when a rendition is missing.
function pickSrc(image: NonNullable<Props["image"]>, size: Props["size"]) {
  if (size === "small") return image.sizes?.thumbnail?.url || image.url;
  return image.sizes?.card?.url || image.url;
}

export function ImageBlockComponent({ image, caption, size = "full" }: Props) {
  if (!image?.url) return null;

  return (
    <Box
      sx={{
        my: 3,
        mx: "auto",
        maxWidth: maxWidthMap[size] || "100%",
      }}
    >
      <Box
        component="img"
        src={pickSrc(image, size)}
        alt={image.alt || caption || ""}
        loading="lazy"
        sx={{
          width: "100%",
          height: "auto",
          borderRadius: 2,
          display: "block",
        }}
      />
      {caption && (
        <Typography
          variant="caption"
          sx={{
            color: "text.secondary",
            display: "block",
            textAlign: "center",
            mt: 1,
          }}
        >
          {caption}
        </Typography>
      )}
    </Box>
  );
}
