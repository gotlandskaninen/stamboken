import type { Block } from "payload";

export const ColumnsBlock: Block = {
  slug: "columns",
  labels: { singular: "Kolumner", plural: "Kolumner" },
  fields: [
    {
      name: "layout",
      type: "select",
      label: "Layout",
      defaultValue: "2-equal",
      options: [
        { label: "2 lika", value: "2-equal" },
        { label: "3 lika", value: "3-equal" },
        { label: "1/3 + 2/3", value: "1-2" },
        { label: "2/3 + 1/3", value: "2-1" },
      ],
    },
    {
      name: "columns",
      type: "array",
      label: "Kolumner",
      maxRows: 3,
      fields: [
        {
          name: "content",
          type: "richText",
          label: "Innehåll",
        },
        {
          name: "image",
          type: "upload",
          relationTo: "media",
          label: "Bild",
        },
      ],
    },
  ],
};
