import { Box } from "@mui/material";

interface Props {
  url?: string;
}

function toEmbedUrl(url: string): string | null {
  // YouTube
  const ytMatch = url.match(
    /(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]+)/,
  );
  if (ytMatch) return `https://www.youtube.com/embed/${ytMatch[1]}`;

  // Vimeo
  const vimeoMatch = url.match(/vimeo\.com\/(\d+)/);
  if (vimeoMatch) return `https://player.vimeo.com/video/${vimeoMatch[1]}`;

  return null;
}

export function EmbedBlockComponent({ url }: Props) {
  if (!url) return null;

  const embedUrl = toEmbedUrl(url);
  if (!embedUrl) return null;

  return (
    <Box
      sx={{
        my: 4,
        position: "relative",
        paddingTop: "56.25%", // 16:9
        borderRadius: 2,
        overflow: "hidden",
      }}
    >
      <Box
        component="iframe"
        src={embedUrl}
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
        allowFullScreen
        sx={{
          position: "absolute",
          top: 0,
          left: 0,
          width: "100%",
          height: "100%",
          border: 0,
        }}
      />
    </Box>
  );
}
