import type { SerializedEditorState } from "@payloadcms/richtext-lexical/lexical";
import { convertLexicalToPlaintext } from "@payloadcms/richtext-lexical/plaintext";
import { getPayload } from "payload";
import config from "@payload-config";

function hasRuleText(content?: SerializedEditorState | null) {
  return (
    !!content &&
    /[\p{L}\p{N}]/u.test(convertLexicalToPlaintext({ data: content }))
  );
}

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
    if (
      !page?.layout?.some(
        (block) =>
          (block.blockType === "richText" && hasRuleText(block.content)) ||
          (block.blockType === "columns" &&
            block.columns?.some(({ content }) => hasRuleText(content))),
      )
    )
      return null;
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
