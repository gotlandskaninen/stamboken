// The CMS text pages share one grid: a margin column for the section
// headings and a text column of about 80 characters beside it. Every block
// lines up with it, so text, photos and galleries have one left edge.
export const TEXT_ROW = {
  display: "grid",
  // The text keeps its width first; the heading column takes what is left,
  // down to 180px. Below md the two stack.
  gridTemplateColumns: { md: "minmax(180px, 1fr) minmax(0, 42rem)" },
  columnGap: 14,
} as const;

// Heading column (280px) + gap + text column.
export const TEXT_MAX_WIDTH = 1008;

// From here there is room for a side column beside the text.
export const WIDE = "@media (min-width: 1360px)";
