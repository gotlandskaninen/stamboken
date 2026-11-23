// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "@/app/(payload)/cms-api/kontoregler/version/route";

const db = vi.hoisted(() => ({ find: vi.fn(), findVersions: vi.fn() }));
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
    updatedAt: "2026-01-02T00:00:00.000Z",
    layout: [
      {
        blockType: "richText",
        content: paragraph("Använd bara ditt eget testkonto."),
      },
    ],
  };
  it("matches the live publication's parent and timestamp and returns only the version ID", async () => {
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
    expect(await response.json()).toEqual({ version: "8" });
    expect(response.headers.get("cache-control")).toBe("no-store");
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
    expect(await (await GET()).json()).toEqual({ version: "8" });
  });
});
