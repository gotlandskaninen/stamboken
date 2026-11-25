// @vitest-environment node
import { createHash } from "node:crypto";
import { renderToStaticMarkup } from "react-dom/server";
import CreateAccountPage from "@/app/(app)/(auth)/auth/skapa-konto/page";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/(payload)/cms-api/kontoregler/version/route";

const db = vi.hoisted(() => ({ find: vi.fn(), findVersions: vi.fn() }));
vi.mock("next/headers", () => ({
  cookies: async () => new Map([["session", "test"]]),
}));
vi.mock("@/lib/code-login-enabled", () => ({
  codeLoginEnabled: async () => true,
}));
vi.mock("@/components/auth/CodeLogin", () => ({ CreateAccount: vi.fn() }));
vi.mock("@payload-config", () => ({ default: {} }));
vi.mock("payload", () => ({ getPayload: async () => db }));

beforeEach(() => {
  vi.resetAllMocks();
});

// The words a reader sees in rendered markup, with block ends as blank lines.
function shownText(markup: string) {
  return markup
    .replace(/<br\s*\/?>/g, "\n")
    .replace(/<\/(h2|p)>/g, "\n\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&amp;/g, "&")
    .trim();
}

describe("published account rules revision", () => {
  const paragraph = (text: string) => ({
    root: {
      children: [{ type: "paragraph", children: [{ type: "text", text }] }],
    },
  });
  const page = {
    id: 3,
    title: "Kontoregler",
    subtitle: "För alla konton",
    updatedAt: "2026-01-02T00:00:00.000Z",
    layout: [
      {
        blockType: "richText",
        content: paragraph("Använd bara ditt eget testkonto."),
      },
    ],
  };
  it("matches the live publication's parent and timestamp and returns the exact text with its version", async () => {
    db.find.mockResolvedValue({ docs: [page] });
    db.findVersions.mockResolvedValue({ docs: [{ id: 8 }] });
    const response = await GET();
    expect(db.find).toHaveBeenCalledWith(
      expect.objectContaining({
        where: {
          slug: { equals: "kontoregler" },
          _status: { equals: "published" },
        },
        overrideAccess: false,
        draft: false,
      }),
    );
    expect(db.findVersions).toHaveBeenCalledWith(
      expect.objectContaining({
        where: {
          parent: { equals: 3 },
          "version._status": { equals: "published" },
          "version.updatedAt": { equals: page.updatedAt },
        },
      }),
    );
    expect(await response.json()).toEqual({
      version: "8",
      text: "Kontoregler\n\nFör alla konton\n\nAnvänd bara ditt eget testkonto.",
    });
    expect(response.headers.get("cache-control")).toBe("no-store");
  });
  it("displays the text that Flask will archive, with its formatting, and binds the form to its UTF-8 digest", async () => {
    // The node shapes the seeded rules use (a bold opening, a mailto link and
    // a site-relative link), plus italics, a line break and an autolink.
    const text = (value: string, format?: number) => ({
      type: "text",
      text: value,
      ...(format ? { format } : {}),
    });
    const link = (url: string, label: string) => ({
      type: "link",
      fields: { url, linkType: "custom", newTab: false },
      children: [text(label)],
    });
    const content = {
      root: {
        children: [
          { type: "paragraph", children: [text("Inledning & syfte.")] },
          {
            type: "paragraph",
            children: [
              text("Kontot är ditt eget.", 1),
              text(" Mejla "),
              link("mailto:test@example.org", "test@example.org"),
              text(" eller "),
              {
                type: "autolink",
                fields: { url: "https://example.org", linkType: "custom" },
                children: [text("example.org")],
              },
              text("."),
            ],
          },
          {
            type: "paragraph",
            children: [
              text("Läs "),
              link("/dataskydd", "policyn"),
              text("."),
              { type: "linebreak" },
              text("Andra raden, ”citerad” och 'enkel'.", 2),
            ],
          },
        ],
      },
    };
    db.find.mockResolvedValue({
      docs: [
        {
          ...page,
          layout: [
            { blockType: "richText", content },
            { blockType: "image", caption: "En bildtext" },
          ],
        },
      ],
    });
    db.findVersions.mockResolvedValue({ docs: [{ id: 8 }] });
    const form = await CreateAccountPage({ searchParams: Promise.resolve({}) });
    const response = await (await GET()).json();
    expect(Object.keys(response).sort()).toEqual(["text", "version"]);
    expect(form.props.rules).toEqual({
      version: response.version,
      sha256: createHash("sha256").update(response.text).digest("hex"),
    });
    const markup = renderToStaticMarkup(form.props.children);
    expect(markup).toContain("<strong>Kontot är ditt eget.</strong>");
    expect(markup).toContain('href="mailto:test@example.org"');
    expect(markup).toContain('href="/dataskydd"');
    expect(markup).toContain("<em>");
    expect(shownText(markup)).toBe(response.text);
  });
  // Content whose rendering would show other words than the plain text: an
  // image with its caption, a struck-out negation, a quote that the plain
  // text runs together, a link to a CMS page, a heading and a list.
  it.each([
    [
      "upload",
      {
        type: "upload",
        value: {
          url: "/media/regel.png",
          mimeType: "image/png",
          caption: "Kontakta styrelsen först.",
        },
      },
    ],
    [
      "strikethrough",
      {
        type: "paragraph",
        children: [
          { type: "text", text: "Du får " },
          { type: "text", text: "inte", format: 4 },
          { type: "text", text: " dela kontot." },
        ],
      },
    ],
    [
      "quote",
      { type: "quote", children: [{ type: "text", text: "ditt lösenord" }] },
    ],
    [
      "internal link",
      {
        type: "paragraph",
        children: [
          {
            type: "link",
            fields: { linkType: "internal", doc: { value: 4 } },
            children: [{ type: "text", text: "sidan" }],
          },
        ],
      },
    ],
    [
      "a link with its own text",
      {
        type: "paragraph",
        children: [
          {
            type: "link",
            text: "Se även ",
            fields: { url: "/ordlista", linkType: "custom" },
            children: [{ type: "text", text: "ordlistan" }],
          },
        ],
      },
    ],
    [
      "an autolink without fields",
      {
        type: "paragraph",
        children: [
          { type: "text", text: "Läs " },
          {
            type: "autolink",
            children: [{ type: "text", text: "example.org" }],
          },
          { type: "text", text: " före registrering." },
        ],
      },
    ],
    [
      "a line break with children",
      {
        type: "paragraph",
        children: [
          { type: "text", text: "Du får" },
          { type: "linebreak", children: [{ type: "text", text: " INTE" }] },
          { type: "text", text: " dela kontot." },
        ],
      },
    ],
    [
      "a text node with children",
      {
        type: "paragraph",
        children: [
          {
            type: "text",
            text: "Synlig",
            children: [{ type: "text", text: " dold" }],
          },
        ],
      },
    ],
    [
      "heading",
      {
        type: "heading",
        tag: "h1",
        children: [{ type: "text", text: "Rubrik" }],
      },
    ],
    [
      "list",
      {
        type: "list",
        listType: "number",
        children: [
          { type: "listitem", children: [{ type: "text", text: "Ett" }] },
        ],
      },
    ],
  ])(
    "shows the hashed plain text instead of rich text with %s",
    async (_name, node) => {
      const content = {
        root: {
          children: [
            {
              type: "paragraph",
              children: [{ type: "text", text: "Dela aldrig", format: 1 }],
            },
            node,
          ],
        },
      };
      db.find.mockResolvedValue({
        docs: [{ ...page, layout: [{ blockType: "richText", content }] }],
      });
      db.findVersions.mockResolvedValue({ docs: [{ id: 8 }] });
      const form = await CreateAccountPage({
        searchParams: Promise.resolve({}),
      });
      const { text } = await (await GET()).json();
      const markup = renderToStaticMarkup(form.props.children);
      expect(markup).not.toMatch(/<(strong|img|s|blockquote|h1|ol|a)\b/);
      expect(markup).not.toContain("Kontakta styrelsen");
      expect(shownText(markup)).toBe(text);
    },
  );
  it.each([[], [{ ...page, layout: [] }]])(
    "does not accept a missing or empty publication",
    async (...docs) => {
      db.find.mockResolvedValue({ docs });
      expect((await GET()).status).toBe(503);
      expect(db.findVersions).not.toHaveBeenCalled();
    },
  );
  it("cannot attest to rules without a matching revision", async () => {
    db.find.mockResolvedValue({ docs: [page] });
    db.findVersions.mockResolvedValue({ docs: [] });
    expect((await GET()).status).toBe(503);
  });
  it.each([
    [{ blockType: "divider" }],
    [{ blockType: "image", caption: "En bildtext" }],
    [{ blockType: "richText", content: paragraph("  \n") }],
  ])(
    "refuses a published revision without readable rule text",
    async (block) => {
      db.find.mockResolvedValue({ docs: [{ ...page, layout: [block] }] });
      db.findVersions.mockResolvedValue({ docs: [{ id: 8 }] });
      expect((await GET()).status).toBe(503);
      expect(db.findVersions).not.toHaveBeenCalled();
    },
  );
  it.each([
    [
      "an empty column",
      [
        {
          blockType: "richText",
          content: paragraph("Använd bara ditt eget testkonto."),
        },
        {
          blockType: "columns",
          columns: [{ content: { root: { children: {} } } }],
        },
      ],
    ],
    [
      "a paragraph whose children are not a list",
      [
        {
          blockType: "richText",
          content: {
            root: {
              children: [
                {
                  type: "paragraph",
                  children: [
                    { type: "text", text: "Använd bara ditt eget testkonto." },
                  ],
                },
                { type: "paragraph", children: "" },
              ],
            },
          },
        },
      ],
    ],
  ])("still offers the rules with %s", async (_name, layout) => {
    db.find.mockResolvedValue({ docs: [{ ...page, layout }] });
    db.findVersions.mockResolvedValue({ docs: [{ id: 8 }] });
    const response = await GET();
    expect(response.status).toBe(200);
    const { text } = await response.json();
    // The text is computed as on main, an empty paragraph's blank line included.
    expect(text.trim()).toBe(
      "Kontoregler\n\nFör alla konton\n\nAnvänd bara ditt eget testkonto.",
    );
    const form = await CreateAccountPage({ searchParams: Promise.resolve({}) });
    expect(form.props.rules.sha256).toBe(
      createHash("sha256").update(text).digest("hex"),
    );
    expect(shownText(renderToStaticMarkup(form.props.children))).toBe(
      text.trim(),
    );
  });
  it("accepts readable rules in a column", async () => {
    const columns = [
      { content: paragraph("Använd bara ditt eget testkonto.") },
    ];
    db.find.mockResolvedValue({
      docs: [{ ...page, layout: [{ blockType: "columns", columns }] }],
    });
    db.findVersions.mockResolvedValue({ docs: [{ id: 8 }] });
    expect(await (await GET()).json()).toEqual({
      version: "8",
      text: "Kontoregler\n\nFör alla konton\n\nAnvänd bara ditt eget testkonto.",
    });
  });
});
