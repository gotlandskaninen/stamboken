import type { Block } from "payload";

export const GalleryBlock: Block = {
  slug: "gallery",
  labels: { singular: "Galleri", plural: "Gallerier" },
  fields: [
    {
      name: "images",
      type: "array",
      label: "Bilder",
      minRows: 2,
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
      ],
    },
  ],
};
