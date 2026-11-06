import type { Block } from "payload";

export const ImageBlock: Block = {
  slug: "image",
  labels: { singular: "Bild", plural: "Bilder" },
  fields: [
    {
      name: "image",
      type: "upload",
      relationTo: "media",
      required: true,
    },
    {
      name: "caption",
      type: "text",
      label: "Bildtext",
    },
    {
      name: "size",
      type: "select",
      label: "Storlek",
      defaultValue: "full",
      options: [
        { label: "Liten", value: "small" },
        { label: "Medium", value: "medium" },
        { label: "Hel bredd", value: "full" },
      ],
    },
  ],
};
