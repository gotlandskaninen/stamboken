import type { SerializedEditorState } from "@payloadcms/richtext-lexical/lexical";
import { convertLexicalToPlaintext } from "@payloadcms/richtext-lexical/plaintext";
import { getPayload } from "payload";
import config from "@payload-config";

type LexicalNode = {
  type?: string;
  text?: unknown;
  format?: number | string;
  fields?: { linkType?: string };
  children?: LexicalNode[];
};
// Bold and italic only: their words are the plain text's words.
const PLAIN_FORMATS = 1 | 2;
// The plain-text converter reads the `text` and `children` it finds, the page
// only what each node type renders, so a node must carry exactly those.
function sameWordsAsText(node: LexicalNode): boolean {
  switch (node.type) {
    case "text":
      return (
        typeof node.text === "string" &&
        node.children === undefined &&
        (Number(node.format ?? 0) & ~PLAIN_FORMATS) === 0
      );
    case "linebreak":
      return node.text === undefined && node.children === undefined;
    case "link":
    case "autolink":
      return (
        node.fields?.linkType === "custom" &&
        node.text === undefined &&
        (node.children ?? []).every(
          (child) => child.type === "text" && sameWordsAsText(child),
        )
      );
    default:
      return false;
  }
}
// Rich text is shown with its formatting only when the member reads exactly
// the words that are hashed: paragraphs of plain, bold or italic text, line
// breaks and links to a typed address. Anything else (images, quotes,
// headings, lists, strikethrough, links to CMS pages) is shown as the plain
// text that is hashed.
function formattable(content: SerializedEditorState) {
  return (content.root?.children ?? []).every(
    (node: LexicalNode) =>
      node.type === "paragraph" &&
      node.text === undefined &&
      (node.children ?? []).every(sameWordsAsText),
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
    if (!page) return null;
    // Only editorial rule text enables acceptance. Captions can accompany it.
    let hasRuleText = false;
    // The page renders each section's content; its text is what is hashed.
    type Section = { content?: SerializedEditorState; text?: string | null };
    function ruleText(content?: SerializedEditorState | null): Section {
      const text = content ? convertLexicalToPlaintext({ data: content }) : "";
      if (/[\p{L}\p{N}]/u.test(text)) hasRuleText = true;
      return {
        content: content && formattable(content) ? content : undefined,
        text,
      };
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
