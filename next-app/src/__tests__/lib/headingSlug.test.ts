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

  it("does not hand out a numbered slug an earlier heading took", () => {
    const slug = headingSlugger();
    expect(slug("Steg 1")).toBe("steg-1");
    expect(slug("Steg")).toBe("steg");
    expect(slug("Steg")).toBe("steg-2");
  });
});

describe("the manual's internal links", () => {
  it("all point at a heading", async () => {
    const { readFile } = await import("node:fs/promises");
    const md = await readFile("public/stamboken/manual/USER_MANUAL.md", "utf8");
    const slug = headingSlugger();
    // The page gives ids to h2-h4 only; every heading still counts for the
    // "-N" numbering, as it does when the page renders.
    const anchors = new Set(
      [...md.matchAll(/^(#{1,6}) (.+)$/gm)]
        .map((m) => [m[1].length, slug(m[2].replace(/[*`]/g, ""))] as const)
        .filter(([level]) => level >= 2 && level <= 4)
        .map(([, id]) => id),
    );
    const links = [...md.matchAll(/\]\(#([^)]+)\)/g)].map((m) => m[1]);
    expect(links.length).toBeGreaterThan(50);
    expect(links.filter((l) => !anchors.has(l))).toEqual([]);
  });
});
