import type { CollectionConfig } from "payload";
import { isEditorOrAdmin } from "../access/isEditorOrAdmin";
import {
  revalidatePagesAfterMediaChange,
  revalidatePagesAfterMediaDelete,
} from "../hooks/revalidateCache";

export const Media: CollectionConfig = {
  slug: "media",
  hooks: {
    afterChange: [revalidatePagesAfterMediaChange],
    afterDelete: [revalidatePagesAfterMediaDelete],
  },
  access: {
    create: isEditorOrAdmin,
    read: () => true,
    update: isEditorOrAdmin,
    delete: isEditorOrAdmin,
  },
  upload: {
    mimeTypes: [
      "image/jpeg",
      "image/png",
      "image/webp",
      "image/svg+xml",
      "application/pdf",
    ],
    staticDir: "/app/uppladdningar/cms",
    imageSizes: [
      { name: "thumbnail", width: 400, height: 300, position: "centre" },
      { name: "card", width: 768, height: 512, position: "centre" },
    ],
    filesRequiredOnCreate: true,
  },
  fields: [
    {
      name: "alt",
      type: "text",
      required: true,
      label: "Alt-text",
    },
    {
      name: "caption",
      type: "text",
      label: "Bildtext",
      admin: {
        description:
          "Visas under bilden i sidhuvudet och i brödtexten. Ange ras (gotlandskanin eller mellerudskanin) och gärna teckning.",
      },
    },
  ],
};
