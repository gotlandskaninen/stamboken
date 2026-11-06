import type { CollectionConfig } from "payload";
import { isEditorOrAdmin } from "../access/isEditorOrAdmin";
import { validateSlug } from "../hooks/validateSlug";
import {
  revalidatePageAfterChange,
  revalidatePageAfterDelete,
} from "../hooks/revalidateCache";
import { RichTextBlock } from "../blocks/RichTextBlock";
import { ImageBlock } from "../blocks/ImageBlock";
import { GalleryBlock } from "../blocks/GalleryBlock";
import { ColumnsBlock } from "../blocks/ColumnsBlock";
import { DividerBlock } from "../blocks/DividerBlock";
import { EmbedBlock } from "../blocks/EmbedBlock";

export const Pages: CollectionConfig = {
  slug: "pages",
  admin: {
    useAsTitle: "title",
    defaultColumns: ["title", "slug", "_status", "updatedAt"],
    livePreview: {
      url: ({ data }) => `/preview/${data.slug}`,
    },
  },
  access: {
    create: isEditorOrAdmin,
    read: ({ req: { user } }) => {
      if (user) return true;
      return { _status: { equals: "published" } };
    },
    update: isEditorOrAdmin,
    delete: isEditorOrAdmin,
  },
  versions: {
    drafts: {
      autosave: { interval: 30000 },
    },
  },
  hooks: {
    beforeValidate: [validateSlug],
    afterChange: [revalidatePageAfterChange],
    afterDelete: [revalidatePageAfterDelete],
  },
  fields: [
    {
      name: "title",
      type: "text",
      required: true,
      label: "Titel",
    },
    {
      name: "subtitle",
      type: "textarea",
      label: "Underrubrik (ingress)",
      admin: {
        description:
          "Kort ingresstext som visas under rubriken i sidhuvudet, t.ex. " +
          '"Eftersom den gamla svenska lantrasen hotades av utrotning…".',
      },
    },
    {
      name: "slug",
      type: "text",
      required: true,
      unique: true,
      label: "URL-slug",
      admin: {
        position: "sidebar",
        description: 'URL-sökväg, t.ex. "om-foreningen"',
      },
    },
    {
      name: "featuredImage",
      type: "upload",
      relationTo: "media",
      label: "Utvald bild (hero-banner)",
    },
    {
      name: "layout",
      type: "blocks",
      label: "Sidinnehåll",
      blocks: [
        RichTextBlock,
        ImageBlock,
        GalleryBlock,
        ColumnsBlock,
        DividerBlock,
        EmbedBlock,
      ],
    },
    {
      name: "meta",
      type: "group",
      label: "SEO",
      admin: { position: "sidebar" },
      fields: [
        { name: "title", type: "text", label: "SEO-titel" },
        { name: "description", type: "textarea", label: "SEO-beskrivning" },
      ],
    },
  ],
};
