import { Box, Grid } from "@mui/material";
import { RichText } from "@payloadcms/richtext-lexical/react";
import { richTextConverters } from "./richTextConverters";

interface Column {
  content?: any;
  image?: { url: string; alt?: string } | string | number | null;
}

interface Props {
  layout?: string;
  columns?: Column[];
  /** The first block on the page starts without a rule above it. */
  first?: boolean;
}

const gridMap: Record<string, number[]> = {
  "2-equal": [6, 6],
  "3-equal": [4, 4, 4],
  "1-2": [4, 8],
  "2-1": [8, 4],
};

function getImageUrl(
  image: Column["image"],
): { url: string; alt: string } | null {
  if (!image) return null;
  if (typeof image === "object" && "url" in image && image.url) {
    return { url: image.url, alt: image.alt || "" };
  }
  return null;
}

export function ColumnsBlockComponent({
  layout = "2-equal",
  columns,
  first = false,
}: Props) {
  if (!columns || columns.length === 0) return null;

  const sizes = gridMap[layout] || gridMap["2-equal"];

  // A column with neither an image nor content (e.g. a photo slot not yet
  // filled) must not leave a blank gutter next to the real content.
  const visibleColumns = columns
    .map((col, i) => ({ col, i, img: getImageUrl(col.image) }))
    .filter(({ col, img }) => img || col.content);

  if (visibleColumns.length === 0) return null;

  return (
    <Grid
      container
      columnSpacing={14}
      rowSpacing={8}
      sx={{
        py: { xs: 7, md: 9 },
        ...(first ? { pt: 0 } : { borderTop: "1px solid var(--sb-line)" }),
        alignItems: "flex-start",
      }}
    >
      {visibleColumns.map(({ col, i, img }) => {
        const size =
          visibleColumns.length === 1
            ? { xs: 12, md: 12 }
            : { xs: 12, md: sizes[i] || 6 };
        return (
          <Grid key={i} size={size}>
            {img && (
              <Box
                component="img"
                src={img.url}
                alt={img.alt}
                sx={{
                  width: "100%",
                  height: "auto",
                  borderRadius: 2,
                  mb: col.content ? 2 : 0,
                }}
              />
            )}
            {col.content && (
              <Box
                sx={{
                  "& p": { mb: 1.5, lineHeight: 1.7 },
                  // Same face and size as the section headings in RichTextBlock.
                  "& h2": {
                    mt: 6,
                    mb: 3,
                    fontFamily: "var(--sb-display)",
                    fontWeight: 400,
                    fontSize: { xs: "24px", md: "26px" },
                    lineHeight: 1.15,
                    letterSpacing: "-0.01em",
                  },
                  "& > :first-of-type": { mt: 0 },
                  "& h3": {
                    mt: 1.5,
                    mb: 0.5,
                    fontWeight: 600,
                    color: "text.secondary",
                  },
                  "& a": { color: "primary.main" },
                }}
              >
                <RichText data={col.content} converters={richTextConverters} />
              </Box>
            )}
          </Grid>
        );
      })}
    </Grid>
  );
}
