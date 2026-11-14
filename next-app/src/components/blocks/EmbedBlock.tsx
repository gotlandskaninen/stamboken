"use client";

import { useState } from "react";
import { Box, Button, Typography } from "@mui/material";

interface Props {
  url?: string;
}

function toEmbed(url: string): { src: string; provider: string } | null {
  const ytMatch = url.match(
    /(?:youtube\.com\/watch\?v=|youtu\.be\/)([a-zA-Z0-9_-]+)/,
  );
  if (ytMatch)
    return {
      src: `https://www.youtube-nocookie.com/embed/${ytMatch[1]}?autoplay=1`,
      provider: "YouTube",
    };

  const vimeoMatch = url.match(/vimeo\.com\/(\d+)/);
  if (vimeoMatch)
    return {
      src: `https://player.vimeo.com/video/${vimeoMatch[1]}?autoplay=1`,
      provider: "Vimeo",
    };

  return null;
}

const fill = {
  position: "absolute",
  top: 0,
  left: 0,
  width: "100%",
  height: "100%",
} as const;

// Nothing is fetched from the video service until the visitor asks for the
// film: the player sets cookies, and the site has no consent banner.
export function EmbedBlockComponent({ url }: Props) {
  const [show, setShow] = useState(false);
  const embed = url ? toEmbed(url) : null;
  if (!embed) return null;

  return (
    <Box
      sx={{
        my: 4,
        position: "relative",
        paddingTop: "56.25%", // 16:9
        borderRadius: 2,
        overflow: "hidden",
        bgcolor: "background.paper",
        border: 1,
        borderColor: "line.main",
      }}
    >
      {show ? (
        <Box
          component="iframe"
          src={embed.src}
          title={`Film från ${embed.provider}`}
          allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
          allowFullScreen
          sx={{ ...fill, border: 0 }}
        />
      ) : (
        <Box
          sx={{
            ...fill,
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 3,
            p: 4,
            textAlign: "center",
          }}
        >
          <Typography sx={{ maxWidth: "32rem", color: "ink.2" }}>
            Filmen visas från {embed.provider}. När du startar den hämtas den
            därifrån, och {embed.provider} kan sätta kakor i din webbläsare.
          </Typography>
          <Button variant="contained" onClick={() => setShow(true)}>
            Visa filmen
          </Button>
        </Box>
      )}
    </Box>
  );
}
