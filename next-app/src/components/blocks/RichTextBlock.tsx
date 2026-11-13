import { Box } from "@mui/material";
import { RichText } from "@payloadcms/richtext-lexical/react";
import { richTextConverters } from "./richTextConverters";

interface Props {
  content: any;
}

export function RichTextBlockComponent({ content }: Props) {
  if (!content) return null;

  return (
    <Box
      sx={{
        mb: 3,
        // About 80 characters a line; the full column gave 110-120.
        maxWidth: "38rem",
        "& h2": {
          mt: 4,
          mb: 1.5,
          fontWeight: 600,
          fontSize: { xs: "1.4rem", md: "1.6rem" },
          borderBottom: "2px solid",
          borderColor: "primary.main",
          pb: 0.5,
          display: "inline-block",
        },
        "& h3": {
          mt: 3,
          mb: 1,
          fontWeight: 600,
          fontSize: { xs: "1.1rem", md: "1.2rem" },
          color: "text.secondary",
        },
        "& p": {
          mb: 2,
          lineHeight: 1.7,
          fontSize: { xs: "1rem", md: "1.05rem" },
        },
        "& a": { color: "primary.main" },
      }}
    >
      <RichText data={content} converters={richTextConverters} />
    </Box>
  );
}
