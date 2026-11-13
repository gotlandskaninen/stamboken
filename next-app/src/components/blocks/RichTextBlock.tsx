import { Box, Typography } from "@mui/material";
import { RichText } from "@payloadcms/richtext-lexical/react";
import { richTextConverters } from "./richTextConverters";
import { TEXT_ROW } from "./textColumn";

interface Props {
  content: any;
  /** The first block on the page starts without a rule above it. */
  first?: boolean;
}

export interface TextSection {
  title: string | null;
  children: any[];
}

// One section per h2. What stands before the first h2 is a section without
// a heading.
export function splitSections(content: any): TextSection[] {
  const sections: TextSection[] = [];
  for (const node of content?.root?.children ?? []) {
    if (node.type === "heading" && node.tag === "h2") {
      sections.push({
        title: (node.children ?? []).map((c: any) => c.text ?? "").join(""),
        children: [],
      });
    } else {
      if (sections.length === 0) sections.push({ title: null, children: [] });
      sections[sections.length - 1].children.push(node);
    }
  }
  return sections;
}

// Each section is a ruled row: on desktop the heading stands in the margin
// column and the text beside it, on phones the heading sits above the text.
export function RichTextBlockComponent({ content, first = false }: Props) {
  if (!content) return null;

  return (
    <>
      {splitSections(content).map((section, i) => (
        <Box
          key={i}
          component="section"
          sx={{
            ...TEXT_ROW,
            rowGap: 3,
            py: { xs: 7, md: 9 },
            ...(first && i === 0
              ? { pt: 0 }
              : { borderTop: "1px solid var(--sb-line)" }),
          }}
        >
          {section.title ? (
            <Typography
              variant="h4"
              component="h2"
              // 26px: a margin column of about 200px holds two or three words.
              sx={{
                m: 0,
                fontWeight: 400,
                fontSize: { xs: "24px", md: "26px" },
              }}
            >
              {section.title}
            </Typography>
          ) : (
            <span />
          )}
          <Box
            sx={{
              minWidth: 0,
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
              "& > :last-child": { mb: 0 },
              "& a": { color: "primary.main" },
            }}
          >
            <RichText
              data={{ root: { ...content.root, children: section.children } }}
              converters={richTextConverters}
            />
          </Box>
        </Box>
      ))}
    </>
  );
}
