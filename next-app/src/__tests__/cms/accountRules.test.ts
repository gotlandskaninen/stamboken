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
    // The node shapes the seeded rules use: a bold opening, a mailto link
    // and an internal link.
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
              text("."),
            ],
          },
          {
            type: "paragraph",
            children: [text("Läs "), link("/dataskydd", "policyn"), text(".")],
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
    // What the member reads is, word for word, what the digest covers.
    const shown = markup
      .replace(/<\/(h2|p)>/g, "\n\n")
      .replace(/<[^>]+>/g, "")
      .replace(/&amp;/g, "&")
      .trim();
    expect(shown).toBe(response.text);
  });
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
