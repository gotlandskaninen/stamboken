import type { CollectionConfig } from "payload";
import { isEditorOrAdmin } from "../access/isEditorOrAdmin";
import {
  revalidateNavAfterChange,
  revalidateNavAfterDelete,
} from "../hooks/revalidateCache";

export const Navigation: CollectionConfig = {
  slug: "navigation",
  admin: {
    useAsTitle: "label",
    defaultColumns: ["label", "order", "hidden"],
  },
  access: {
    create: isEditorOrAdmin,
    read: () => true,
    update: isEditorOrAdmin,
    delete: isEditorOrAdmin,
  },
  hooks: {
    afterChange: [revalidateNavAfterChange],
    afterDelete: [revalidateNavAfterDelete],
  },
  fields: [
    { name: "label", type: "text", required: true, label: "Menytext" },
    {
      name: "page",
      type: "relationship",
      relationTo: "pages",
      label: "Intern sida",
      admin: { description: "Välj en sida ELLER ange extern URL nedan" },
    },
    { name: "externalUrl", type: "text", label: "Extern URL" },
    { name: "subtitle", type: "text", label: "Underrubrik (dropdown)" },
    {
      name: "image",
      type: "upload",
      relationTo: "media",
      label: "Bild (dropdown)",
    },
    {
      name: "linkTarget",
      type: "select",
      defaultValue: "_self",
      options: [
        { label: "Samma fönster", value: "_self" },
        { label: "Nytt fönster", value: "_blank" },
      ],
    },
    {
      name: "order",
      type: "number",
      required: true,
      defaultValue: 0,
      label: "Sorteringsordning",
    },
    {
      name: "parent",
      type: "relationship",
      relationTo: "navigation",
      label: "Förälder (dropdown)",
    },
    {
      name: "hidden",
      type: "checkbox",
      defaultValue: false,
      label: "Dölj från navigation",
    },
  ],
};
