import { describe, it, expect } from "vitest";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const tokensPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../styles/tokens.css",
);
const handoffTokensPath = path.resolve(
  path.dirname(fileURLToPath(import.meta.url)),
  "../../../../docs/design/design_handoff_min_besattning/tokens.css",
);

const sanctionedFontTokens = {
  "--sb-display": "--font-source-serif",
  "--sb-body": "--font-ibm-plex-sans",
  "--sb-mono": "--font-ibm-plex-mono",
} as const;

function normalizeValue(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}

/** The :root block only — mode overrides such as `[data-mode="demo"]` come after it. */
function rootBlock(css: string): string {
  const start = css.indexOf(":root {");
  const end = css.indexOf("\n}", start);
  return start === -1 || end === -1 ? css : css.slice(start, end + 2);
}

function extractSbTokens(css: string): Record<string, string> {
  return Object.fromEntries(
    [...rootBlock(css).matchAll(/(--sb-[\w-]+)\s*:\s*([^;]+);/g)].map(
      ([, name, value]) => [name, normalizeValue(value)],
    ),
  );
}

function extractClassSelectors(css: string): Set<string> {
  const cssWithoutCommentsOrImports = css
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/@import\s+url\([^)]*\);/g, "");

  return new Set(
    [...cssWithoutCommentsOrImports.matchAll(/\.[A-Za-z_-][\w-]*/g)]
      .map(([selector]) => selector)
      .filter((selector) => selector !== ".sb-root"),
  );
}

function extractFontNames(fontStack: string): string[] {
  return fontStack
    .split(",")
    .map((fontName) => fontName.trim().replace(/^["']|["']$/g, ""));
}

function removeNextFontPrefix(fontStack: string, fontVariable: string): string {
  return (
    fontStack
      // nosemgrep: javascript.lang.security.audit.detect-non-literal-regexp.detect-non-literal-regexp -- fontVariable is a hardcoded test constant, not user input
      .replace(new RegExp(`^var\\(${fontVariable},\\s*`), "")
      .replace(/\)(?=,)/, "")
  );
}

describe("tokens.css adaptation (DS-01)", () => {
  const css = fs.readFileSync(tokensPath, "utf-8");
  const handoffCss = fs.readFileSync(handoffTokensPath, "utf-8");

  it("has no Google Fonts @import (fonts come from next/font)", () => {
    expect(css).not.toContain("@import");
    expect(css).not.toContain("fonts.googleapis.com");
  });

  it("resolves font families via the next/font CSS variables", () => {
    expect(css).toMatch(/--sb-display:\s*var\(--font-source-serif/);
    expect(css).toMatch(/--sb-body:\s*var\(--font-ibm-plex-sans/);
    expect(css).toMatch(/--sb-mono:\s*var\(--font-ibm-plex-mono/);
  });

  it("applies base styles at body level instead of .sb-root", () => {
    expect(css).not.toContain(".sb-root");
    expect(css).toMatch(/body\s*\{[^}]*background: var\(--sb-paper\);/s);
  });

  it("keeps the core token values from the handoff", () => {
    expect(css).toMatch(/--sb-skog:\s*#2F4A32/);
    expect(css).toMatch(/--sb-paper:\s*#F4F1EA/);
    expect(css).toMatch(/--sb-card:\s*#FBF9F3/);
    expect(css).toMatch(/--sb-lera:\s*#B85C38/);
    expect(css).toMatch(/--sb-ease: cubic-bezier\(0\.2, 0\.7, 0\.2, 1\)/);
  });

  it("matches every handoff token except sanctioned next/font adaptations", () => {
    const appTokens = extractSbTokens(css);
    const handoffTokens = extractSbTokens(handoffCss);
    const adaptedTokenNames = Object.keys(sanctionedFontTokens);

    expect(
      Object.fromEntries(
        Object.entries(appTokens).filter(
          ([name]) => !adaptedTokenNames.includes(name),
        ),
      ),
    ).toEqual(
      Object.fromEntries(
        Object.entries(handoffTokens).filter(
          ([name]) => !adaptedTokenNames.includes(name),
        ),
      ),
    );

    for (const [tokenName, fontVariable] of Object.entries(
      sanctionedFontTokens,
    )) {
      const appFontStack = appTokens[tokenName];
      const handoffFontStack = handoffTokens[tokenName];

      expect(appFontStack).toMatch(
        // nosemgrep: javascript.lang.security.audit.detect-non-literal-regexp.detect-non-literal-regexp -- fontVariable is a hardcoded test constant, not user input
        new RegExp(`^var\\(${fontVariable}(?:,|\\))`),
      );
      expect(handoffFontStack).toBeDefined();
      expect(
        extractFontNames(removeNextFontPrefix(appFontStack, fontVariable)),
      ).toEqual(extractFontNames(handoffFontStack));
    }
  });

  it("ships every handoff class selector without .sb-root scoping", () => {
    const appSelectors = extractClassSelectors(css);
    const missingSelectors = [...extractClassSelectors(handoffCss)].filter(
      (selector) => !appSelectors.has(selector),
    );

    expect(missingSelectors).toEqual([]);
  });

  it("ships the sb primitives used by the shell and pages", () => {
    for (const cls of [
      ".sb-btn",
      ".sb-card",
      ".sb-badge",
      ".sb-input",
      ".sb-meta",
      ".sb-eyebrow",
      ".sb-stat-num",
      ".sb-stat-label",
      ".sb-tag-dot",
      ".sb-link",
      ".sb-placeholder",
    ]) {
      expect(css).toContain(cls);
    }
  });
});
