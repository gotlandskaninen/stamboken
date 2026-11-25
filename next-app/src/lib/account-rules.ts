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
    // The page renders each section's content; its text is what is hashed.
    type Section = { content?: SerializedEditorState; text?: string | null };
    function ruleText(content?: SerializedEditorState | null): Section {
      const text = content ? convertLexicalToPlaintext({ data: content }) : "";
      if (/[\p{L}\p{N}]/u.test(text)) hasRuleText = true;
      return { content: content ?? undefined, text };
    }
    const sections = (page.layout ?? []).flatMap((block): Section[] => {
      switch (block.blockType) {
        case "richText":
          return [ruleText(block.content)];
        case "columns":
          return (block.columns ?? []).map(({ content }) => ruleText(content));
        case "image":
          return [{ text: block.caption }];
        case "gallery":
          return (block.images ?? []).map(({ caption }) => ({ text: caption }));
        default:
          return [];
      }
    });
    if (!hasRuleText) return null;
    const text = [page.title, page.subtitle, ...sections.map((s) => s.text)]
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
    return revision
      ? {
          version: String(revision.id),
          text,
          title: page.title,
          subtitle: page.subtitle,
          sections: sections.filter((s) => s.text),
        }
      : null;
  } catch {
    return null;
  }
}
