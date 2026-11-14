import { Box } from "@mui/material";
import { RichTextBlockComponent } from "./RichTextBlock";
import { ImageBlockComponent } from "./ImageBlock";
import { GalleryBlockComponent } from "./GalleryBlock";
import { ColumnsBlockComponent } from "./ColumnsBlock";
import { DividerBlockComponent } from "./DividerBlock";
import { EmbedBlockComponent } from "./EmbedBlock";
import { TEXT_MAX_WIDTH, TEXT_ROW } from "./textColumn";

const blockComponents: Record<string, React.ComponentType<any>> = {
  richText: RichTextBlockComponent,
  image: ImageBlockComponent,
  gallery: GalleryBlockComponent,
  columns: ColumnsBlockComponent,
  divider: DividerBlockComponent,
  embed: EmbedBlockComponent,
};

interface RenderBlocksProps {
  blocks: Array<{ blockType: string; id?: string; [key: string]: unknown }>;
}

export function RenderBlocks({ blocks }: RenderBlocksProps) {
  if (!blocks || blocks.length === 0) return null;

  return (
    <Box sx={{ maxWidth: TEXT_MAX_WIDTH }}>
      {blocks.map((block, i) => {
        const Component = blockComponents[block.blockType];
        if (!Component) return null;
        const key = block.id || i;
        if (block.blockType === "richText")
          return <Component key={key} {...block} first={i === 0} />;
        // Columns span both the heading and the text column.
        if (block.blockType === "columns")
          return <Component key={key} {...block} first={i === 0} />;
        // Photos, galleries and the rest line up with the text column.
        return (
          <Box key={key} sx={{ ...TEXT_ROW, mb: 6 }}>
            <Box sx={{ gridColumn: { md: 2 }, minWidth: 0 }}>
              <Component {...block} />
            </Box>
          </Box>
        );
      })}
    </Box>
  );
}
