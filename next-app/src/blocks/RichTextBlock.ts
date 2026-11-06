import type { Block } from "payload";

export const RichTextBlock: Block = {
  slug: "richText",
  labels: { singular: "Text", plural: "Text" },
  fields: [
    {
      name: "content",
      type: "richText",
      required: true,
    },
  ],
};
