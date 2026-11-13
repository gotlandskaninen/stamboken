import { describe, expect, it } from "vitest";
import { splitSections } from "@/components/blocks/RichTextBlock";

const text = (t: string) => ({ type: "text", text: t });
const p = (t: string) => ({ type: "paragraph", children: [text(t)] });
const h = (tag: string, ...parts: string[]) => ({
  type: "heading",
  tag,
  children: parts.map(text),
});

describe("splitSections", () => {
  it("starts a section at every h2 and keeps what follows under it", () => {
    const sections = splitSections({
      root: {
        children: [
          p("Ingress"),
          h("h2", "Varför ", "vi finns"),
          p("Ett"),
          h("h3", "Underrubrik"),
          p("Två"),
          h("h2", "Medlemmarna"),
        ],
      },
    });
    expect(sections.map((s) => s.title)).toEqual([
      null,
      "Varför vi finns",
      "Medlemmarna",
    ]);
    expect(sections.map((s) => s.children.length)).toEqual([1, 3, 0]);
    expect(sections[1].children[1].tag).toBe("h3");
  });

  it("gives no sections for empty content", () => {
    expect(splitSections({ root: { children: [] } })).toEqual([]);
    expect(splitSections(null)).toEqual([]);
  });
});
