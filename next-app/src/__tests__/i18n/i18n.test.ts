import { describe, it, expect, beforeAll } from "vitest";
import i18n from "i18next";

// Import translation files to validate structure
import sv from "../../../messages/sv.json";
import en from "../../../messages/en.json";
import de from "../../../messages/de.json";

// Trigger i18n initialization
beforeAll(async () => {
  await import("@/i18n");
});

describe("i18n configuration", () => {
  it("has sv as default language", () => {
    expect(i18n.language).toBe("sv");
  });

  it("has sv as fallback language", () => {
    const fallback = i18n.options.fallbackLng;
    // fallbackLng can be string or array
    if (Array.isArray(fallback)) {
      expect(fallback).toContain("sv");
    } else {
      expect(fallback).toBe("sv");
    }
  });

  it("has three languages configured: sv, en, de", () => {
    const languages = Object.keys(i18n.options.resources || {});
    expect(languages).toContain("sv");
    expect(languages).toContain("en");
    expect(languages).toContain("de");
    expect(languages).not.toContain("fr");
    expect(languages).not.toContain("nl");
  });

  it("returns Swedish text by default", () => {
    expect(i18n.t("common.loading")).toBe("Laddar...");
  });

  it("returns English text when language is en", async () => {
    await i18n.changeLanguage("en");
    expect(i18n.t("common.loading")).toBe("Loading...");
    // Reset
    await i18n.changeLanguage("sv");
  });

  it("returns German text when language is de", async () => {
    await i18n.changeLanguage("de");
    expect(i18n.t("common.loading")).toBe("Laden...");
    // Reset
    await i18n.changeLanguage("sv");
  });
});

describe("translation file structure", () => {
  it("all three files have matching top-level keys", () => {
    const svKeys = Object.keys(sv).sort();
    const enKeys = Object.keys(en).sort();
    const deKeys = Object.keys(de).sort();
    expect(enKeys).toEqual(svKeys);
    expect(deKeys).toEqual(svKeys);
  });

  it("all files have required sections", () => {
    const required = ["common", "sidebar", "auth", "status", "settings"];
    for (const key of required) {
      expect(sv).toHaveProperty(key);
      expect(en).toHaveProperty(key);
      expect(de).toHaveProperty(key);
    }
  });

  it("Swedish sidebar labels use Swedish text", () => {
    const sidebar = sv.sidebar as Record<string, string>;
    expect(sidebar.minBesattning).toBe("Min besättning");
    expect(sidebar.genetik).toBe("Genetik");
    expect(sidebar.profil).toBe("Profil");
    expect(sidebar.stamboken).toBe("Stamboken");
  });
});
