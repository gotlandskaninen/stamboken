import { Container } from "@mui/material";
import { RichTextBlockComponent } from "./RichTextBlock";
import { ImageBlockComponent } from "./ImageBlock";
import { GalleryBlockComponent } from "./GalleryBlock";
import { ColumnsBlockComponent } from "./ColumnsBlock";
import { DividerBlockComponent } from "./DividerBlock";
import { EmbedBlockComponent } from "./EmbedBlock";

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
    <Container maxWidth="md" sx={{ py: { xs: 4, md: 6 } }}>
      {blocks.map((block, i) => {
        const Component = blockComponents[block.blockType];
        if (!Component) return null;
        return <Component key={block.id || i} {...block} />;
      })}
    </Container>
  );
}
