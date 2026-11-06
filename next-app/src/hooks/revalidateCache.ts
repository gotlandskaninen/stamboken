import { revalidatePath, revalidateTag } from "next/cache";
import type {
  CollectionAfterChangeHook,
  CollectionAfterDeleteHook,
} from "payload";

// Wrapped in try/catch because Payload's afterChange hooks can fire during
// SSR render (e.g. admin create page), where revalidateTag is not allowed
// in Next.js 15.5+. The revalidation is best-effort — it works for normal
// API mutations but silently skips during render context.
function safeRevalidatePath(path: string) {
  try {
    revalidatePath(path);
  } catch {
    // Called during render — skip
  }
}

function safeRevalidateTag(
  tag: string,
  profile: string | { expire: number } = "default",
) {
  try {
    revalidateTag(tag, profile);
  } catch {
    // Called during render — skip
  }
}

export const revalidatePageAfterChange: CollectionAfterChangeHook = ({
  doc,
  previousDoc,
}) => {
  if (doc.slug) {
    safeRevalidatePath(`/${doc.slug}`);
    safeRevalidateTag(`page-${doc.slug}`);
  }
  // On a slug rename, also invalidate the OLD path/tag so the previous URL
  // stops serving stale cached content.
  if (previousDoc?.slug && previousDoc.slug !== doc.slug) {
    safeRevalidatePath(`/${previousDoc.slug}`);
    safeRevalidateTag(`page-${previousDoc.slug}`);
  }
  safeRevalidateTag("navigation");
  return doc;
};

export const revalidatePageAfterDelete: CollectionAfterDeleteHook = ({
  doc,
}) => {
  if (doc.slug) {
    safeRevalidatePath(`/${doc.slug}`);
    safeRevalidateTag(`page-${doc.slug}`);
  }
  safeRevalidateTag("navigation");
  return doc;
};

// Cached pages embed their Media docs (hero, inline images) and the cached
// navigation embeds the dropdown image url, so a changed alt-text, caption or
// replaced file must invalidate every page and the navigation, not one slug.
// Expire immediately ("default" is stale-while-revalidate): Payload deletes the
// replaced file, so the first read after the change must not see its old url.
const EXPIRE_NOW = { expire: 0 };

export const revalidatePagesAfterMediaChange: CollectionAfterChangeHook = ({
  doc,
}) => {
  safeRevalidateTag("pages", EXPIRE_NOW);
  safeRevalidateTag("navigation", EXPIRE_NOW);
  return doc;
};

export const revalidatePagesAfterMediaDelete: CollectionAfterDeleteHook = ({
  doc,
}) => {
  safeRevalidateTag("pages", EXPIRE_NOW);
  safeRevalidateTag("navigation", EXPIRE_NOW);
  return doc;
};

export const revalidateNavAfterChange: CollectionAfterChangeHook = ({
  doc,
}) => {
  safeRevalidateTag("navigation");
  return doc;
};

export const revalidateNavAfterDelete: CollectionAfterDeleteHook = ({
  doc,
}) => {
  safeRevalidateTag("navigation");
  return doc;
};
