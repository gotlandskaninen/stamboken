import type { CollectionBeforeValidateHook } from "payload";

// Keep in sync with: top-level app routes that stay code (admin, auth, stamboken,
// stamboken-online, medlemsforum, bli-genbank, preview) and nginx-owned paths (api, api-test,
// cms-api, cms-graphql, v2, uppladdningar). Editorial slugs are intentionally NOT reserved
// — they are served from the CMS via [slug].
const RESERVED_SLUGS = new Set([
  "admin",
  "ansok",
  "api",
  "api-test",
  "cms-api",
  "cms-graphql",
  "auth",
  "stamboken",
  "stamboken-online",
  "medlem",
  "medlemsforum",
  "bli-genbank",
  "v2",
  "uppladdningar",
  "_next",
  "static",
  "favicon.ico",
  "robots.txt",
  "sitemap.xml",
  "error",
  "not-found",
  "preview",
]);

export const validateSlug: CollectionBeforeValidateHook = ({ data }) => {
  if (data?.slug && RESERVED_SLUGS.has(data.slug)) {
    throw new Error(
      `Slug "${data.slug}" is reserved and cannot be used. Reserved: ${[...RESERVED_SLUGS].join(", ")}`,
    );
  }
  return data;
};
