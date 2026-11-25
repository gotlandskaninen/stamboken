import "@/i18n";
import i18n from "i18next";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { UserContext } from "@/lib/user-context";
import { headingSlugger } from "@/lib/headingSlug";
import {
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
const admin = { ...member, is_admin: true };
const USERS = { member, manager, matrikelAdmin, admin };

const everywhere = () => document.body;
const ids = (
  user: UserContext,
  find: (selector: string) => Element | null = everywhere,
) => stepsFor(user, find).map((s) => s.id);
const step = (user: UserContext, id: string) =>
  stepsFor(user, everywhere).find((s) => s.id === id);

describe("stepsFor", () => {
  it("gives an ordinary member no role, mode or admin steps", () => {
    const shown = ids(member);
    for (const id of ["mode", "roles", "adminPage", "matrikelPage"])
      expect(shown).not.toContain(id);
    expect(shown).toContain("tyckTill");
  });

  it("adds the mode switch and the role steps for a manager", () => {
    expect(ids(manager)).toEqual(
      expect.arrayContaining(["mode", "roles", "adminPage", "matrikelPage"]),
    );
  });

  it("gives the role step to those who keep the matrikel", () => {
    expect(ids(matrikelAdmin)).toContain("roles");
    expect(ids(admin)).toContain("roles");
  });

  it("promises editing and the guide only to those who keep the matrikel", () => {
    expect(step(manager, "matrikelPage")).toMatchObject({
      textKey: "matrikelPage.textRead",
      href: null,
    });
    for (const user of [matrikelAdmin, admin])
      expect(step(user, "matrikelPage")).toMatchObject({
        textKey: "matrikelPage.text",
        href: "/medlem/guide#matrikeln",
      });
  });

  it("links Adminpanelen to each role's own part", () => {
    const href = (user: UserContext) => step(user, "roles")!.href;
    expect(href(admin)).toBe("/stamboken-online/manual#adminpanel");
    expect(href(manager)).toBe(
      "/stamboken-online/manual#adminpanelen-för-genbanksansvarig",
    );
    expect(href(matrikelAdmin)).toBe("/medlem/guide#matrikeln");
    expect(step(matrikelAdmin, "adminPage")!.href).toBe(
      "/medlem/guide#matrikeln",
    );
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
    let shown: Element = link;
    vi.spyOn(Element.prototype, "getClientRects").mockImplementation(function (
      this: Element,
    ) {
      return (this === shown ? [{}] : []) as unknown as DOMRectList;
    });
    const sel = '[data-tour="nav-profil"], [data-tour="menu"]';
    expect(visibleTarget(sel)).toBe(link);
    // Mobile: the nav is hidden, the menu button stands in.
    shown = menu;
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

describe("the steps' texts and links, for every role", () => {
  const docs: Record<string, string> = {
    "/stamboken-online/manual": "public/stamboken/manual/USER_MANUAL.md",
    "/medlem/guide": "content/matrikel-guide/GUIDE.md",
  };

  it.each(Object.entries(USERS))("are all there for %s", async (_, user) => {
    for (const s of stepsFor(user, everywhere)) {
      for (const key of [`${s.id}.title`, s.textKey])
        expect(i18n.exists(`tour.steps.${key}`, { lng: "sv" }), key).toBe(true);
      if (!s.href) continue;
      const [path, anchor] = s.href.split("#");
      const md = await readFile(docs[path], "utf8");
      const slug = headingSlugger();
      const anchors = [...md.matchAll(/^#{1,6} (.+)$/gm)].map((m) =>
        slug(m[1]),
      );
      expect(anchors, s.href).toContain(anchor);
    }
  });
});
