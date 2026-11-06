import type { Block } from "payload";

export const DividerBlock: Block = {
  slug: "divider",
  labels: { singular: "Avdelare", plural: "Avdelare" },
  fields: [
    {
      name: "style",
      type: "select",
      label: "Stil",
      defaultValue: "line",
      options: [
        { label: "Linje", value: "line" },
        { label: "Mellanrum", value: "space" },
      ],
    },
  ],
};
