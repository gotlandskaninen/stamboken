import type { Block } from "payload";

export const EmbedBlock: Block = {
  slug: "embed",
  labels: { singular: "Inbäddning", plural: "Inbäddningar" },
  fields: [
    {
      name: "url",
      type: "text",
      required: true,
      label: "URL (YouTube, Vimeo, etc.)",
    },
  ],
};
