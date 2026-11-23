import { getPayload } from "payload";
import config from "@payload-config";

// Match the current public document to its exact version. A newer draft, an
// old publication under a former slug, or a removed page cannot supply rules.
export async function getAccountRules() {
  try {
    const payload = await getPayload({ config });
    const {
      docs: [page],
    } = await payload.find({
      collection: "pages",
      where: {
        slug: { equals: "kontoregler" },
        _status: { equals: "published" },
      },
      draft: false,
      overrideAccess: false,
      limit: 1,
    });
    if (!page?.layout?.length) return null;
    const {
      docs: [revision],
    } = await payload.findVersions({
      collection: "pages",
      where: {
        parent: { equals: page.id },
        "version._status": { equals: "published" },
        "version.updatedAt": { equals: page.updatedAt },
      },
      depth: 0,
      sort: "-id",
      limit: 1,
    });
    return revision ? { version: String(revision.id), page } : null;
  } catch {
    return null;
  }
}
