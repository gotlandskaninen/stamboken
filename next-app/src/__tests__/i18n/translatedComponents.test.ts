import { beforeAll, describe, expect, it } from "vitest";
import i18n from "i18next";
import { NAV_ITEMS } from "@/components/shell/nav-items";

beforeAll(async () => {
  await import("@/i18n");
});

describe("NAV_ITEMS translations", () => {
  it("translates all dashboard navigation labels to Swedish", async () => {
    await i18n.changeLanguage("sv");

    expect(NAV_ITEMS.map((item) => i18n.t(item.i18nKey))).toEqual([
      "Min besättning",
      "Alla kaniner",
      "Genetik",
      "Provparning",
      "Profil",
    ]);
  });

  it("translates all dashboard navigation labels to English", async () => {
    await i18n.changeLanguage("en");

    expect(NAV_ITEMS.map((item) => i18n.t(item.i18nKey))).toEqual([
      "My Herd",
      "All Rabbits",
      "Genetics",
      "Test mating",
      "Profile",
    ]);

    await i18n.changeLanguage("sv");
  });
});
