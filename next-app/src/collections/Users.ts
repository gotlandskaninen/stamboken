import type { CollectionConfig } from "payload";
import { isAdmin } from "../access/isAdmin";
import { flaskSessionStrategy } from "../auth/flaskSessionStrategy";

export const Users: CollectionConfig = {
  slug: "users",
  auth: {
    disableLocalStrategy: true,
    useAPIKey: true,
    strategies: [flaskSessionStrategy],
  },
  admin: { useAsTitle: "email" },
  access: {
    create: isAdmin,
    read: ({ req: { user } }) => {
      if (user?.role === "admin") return true;
      // Editors must read their own doc (Payload's /me endpoint needs this)
      if (user) return { id: { equals: user.id } };
      return false;
    },
    update: isAdmin,
    delete: isAdmin,
  },
  fields: [
    {
      name: "email",
      type: "email",
      required: true,
      unique: true,
      label: "E-post (Google-konto i Stamboken)",
    },
    {
      name: "role",
      type: "select",
      required: true,
      defaultValue: "editor",
      options: [
        { label: "Admin", value: "admin" },
        { label: "Redigerare", value: "editor" },
      ],
    },
  ],
};
