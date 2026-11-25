import "@/i18n";
import i18n from "i18next";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { UserContext } from "@/lib/user-context";
import { headingSlugger } from "@/lib/headingSlug";

import {
  TOUR_STEPS,
  answerOffer,
  shouldOffer,
  stepsFor,
  visibleTarget,
} from "@/components/tour/tour";

const member = {
  id: 7,
  is_admin: false,
  is_manager: null,
  is_owner: ["G9999"],
  is_matrikel_admin: false,
  v2_prod_access: false,
} as unknown as UserContext;
const manager = { ...member, is_manager: [1], v2_prod_access: true };
const matrikelAdmin = { ...member, is_matrikel_admin: true };

const everywhere = () => document.body;
const ids = (
  user: UserContext,
  find: (selector: string) => Element | null = everywhere,
) => stepsFor(user, find).map((s) => s.id);

describe("stepsFor", () => {
  it("leaves out the mode switch and the role step for an ordinary member", () => {
    expect(ids(member)).not.toContain("mode");
    expect(ids(member)).not.toContain("roles");
    expect(ids(member)).toContain("tyckTill");
  });

  it("adds the mode switch and the role step for a manager", () => {
    expect(ids(manager)).toEqual(expect.arrayContaining(["mode", "roles"]));
  });

  it("gives the role step to those who keep the matrikel", () => {
    expect(ids(matrikelAdmin)).toContain("roles");
    expect(ids({ ...member, is_admin: true })).toContain("roles");
  });

  it("skips steps whose target is not on the page, in order", () => {
    const onPage = new Set(['[data-tour="rabbit-card"]']);
    const find = (sel: string) => (onPage.has(sel) ? document.body : null);
    expect(ids(member, find)).toEqual(["kanin"]);
    expect(ids(member, () => null)).toEqual([]);
  });
});

describe("visibleTarget", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
  });

  it("takes the first match that is on screen", () => {
    document.body.innerHTML =
      '<button data-tour="menu"></button><a data-tour="nav-profil"></a>';
    const [menu, link] = document.body.children;
    const shown = (el: Element) => (el === link ? [{}] : []);
    vi.spyOn(Element.prototype, "getClientRects").mockImplementation(function (
      this: Element,
    ) {
      return shown(this) as unknown as DOMRectList;
    });
    const sel = '[data-tour="nav-profil"], [data-tour="menu"]';
    expect(visibleTarget(sel)).toBe(link);
    // Mobile: the nav is hidden, the menu button stands in.
    vi.mocked(Element.prototype.getClientRects).mockImplementation(function (
      this: Element,
    ) {
      return (this === menu ? [{}] : []) as unknown as DOMRectList;
    });
    expect(visibleTarget(sel)).toBe(menu);
  });
});

describe("the offer's memory", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.restoreAllMocks());

  it("asks each user until they answer", () => {
    expect(shouldOffer(1)).toBe(true);
    answerOffer(1);
    expect(shouldOffer(1)).toBe(false);
    expect(shouldOffer(2)).toBe(true);
  });

  it("does not ask when the browser cannot remember the answer", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(shouldOffer(1)).toBe(false);
  });
});

describe("the steps' texts and links", () => {
  it("has a Swedish title and text for every step", () => {
    for (const step of TOUR_STEPS) {
      const keys = [`${step.id}.title`, `${step.id}.text`];
      for (const key of keys) {
        expect(i18n.exists(`tour.steps.${key}`, { lng: "sv" }), key).toBe(true);
      }
    }
  });

  it("links every step to a heading that exists", async () => {
    const docs: Record<string, string> = {
      "/stamboken-online/manual": "public/stamboken/manual/USER_MANUAL.md",
      "/medlem/guide": "content/matrikel-guide/GUIDE.md",
    };
    for (const step of TOUR_STEPS) {
      const [path, anchor] = step.href.split("#");
      const md = await readFile(docs[path], "utf8");
      const slug = headingSlugger();
      const anchors = [...md.matchAll(/^#{1,6} (.+)$/gm)].map((m) =>
        slug(m[1]),
      );
      expect(anchors, step.href).toContain(anchor);
    }
  });
});
