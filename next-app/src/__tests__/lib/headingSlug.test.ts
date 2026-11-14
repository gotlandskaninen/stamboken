import { describe, it, expect } from "vitest";
import { headingSlugger } from "@/lib/headingSlug";

describe("headingSlugger", () => {
  it("matches the anchors in the manual's table of contents", () => {
    const slug = headingSlugger();
    expect(slug("Del 0 – Komma igång")).toBe("del-0--komma-igång");
    expect(slug("Användare – redigera")).toBe("användare--redigera");
    expect(slug("Testmiljön och riktiga stamboken")).toBe(
      "testmiljön-och-riktiga-stamboken",
    );
    expect(slug("När pappret och Stamboken har olika individnummer")).toBe(
      "när-pappret-och-stamboken-har-olika-individnummer",
    );
  });

  it("numbers repeated headings like GitHub", () => {
    const slug = headingSlugger();
    expect(slug("Skärmarna")).toBe("skärmarna");
    expect(slug("Skärmarna")).toBe("skärmarna-1");
    expect(slug("Skärmarna")).toBe("skärmarna-2");
  });
});

describe("the manual's internal links", () => {
  it("all point at a heading", async () => {
    const { readFile } = await import("node:fs/promises");
    const md = await readFile("public/stamboken/manual/USER_MANUAL.md", "utf8");
    const slug = headingSlugger();
    const anchors = new Set(
      [...md.matchAll(/^#{1,6} (.+)$/gm)].map((m) =>
        slug(m[1].replace(/[*`]/g, "")),
      ),
    );
    const links = [...md.matchAll(/\]\(#([^)]+)\)/g)].map((m) => m[1]);
    expect(links.length).toBeGreaterThan(50);
    expect(links.filter((l) => !anchors.has(l))).toEqual([]);
  });
});
