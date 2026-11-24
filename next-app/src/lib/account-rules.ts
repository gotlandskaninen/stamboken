import type { SerializedEditorState } from "@payloadcms/richtext-lexical/lexical";
import { convertLexicalToPlaintext } from "@payloadcms/richtext-lexical/plaintext";
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
    if (!page) return null;
    // Only editorial rule text enables acceptance. Captions can accompany it.
    let hasRuleText = false;
    function ruleText(content?: SerializedEditorState | null) {
      const text = content ? convertLexicalToPlaintext({ data: content }) : "";
      if (/[\p{L}\p{N}]/u.test(text)) hasRuleText = true;
      return text;
    }
    const sections = (page.layout ?? []).flatMap((block) => {
      switch (block.blockType) {
        case "richText":
          return [ruleText(block.content)];
        case "columns":
          return (block.columns ?? []).map(({ content }) => ruleText(content));
        case "image":
          return [block.caption];
        case "gallery":
          return (block.images ?? []).map(({ caption }) => caption);
        default:
          return [];
      }
    });
    if (!hasRuleText) return null;
    const text = [page.title, page.subtitle, ...sections]
      .filter(Boolean)
      .join("\n\n");
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
    return revision ? { version: String(revision.id), text } : null;
  } catch {
    return null;
  }
}
