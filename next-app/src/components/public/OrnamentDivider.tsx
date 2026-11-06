import { Box } from "@mui/material";

export function OrnamentDivider() {
  return (
    <Box
      sx={{
        textAlign: "center",
        fontFamily: "'Source Serif 4', Georgia, serif",
        color: "ink.3",
        fontSize: "24px",
        letterSpacing: "0.6em",
        lineHeight: 1,
        userSelect: "none",
        py: 8,
      }}
      aria-hidden="true"
    >
      &middot; &middot; &#10022; &middot; &middot;
    </Box>
  );
}
