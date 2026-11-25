import "@testing-library/jest-dom/vitest";
import "@/i18n";
import i18n from "i18next";
import { readFile } from "node:fs/promises";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { UserContext } from "@/lib/user-context";
import { headingSlugger } from "@/lib/headingSlug";

const mocks = vi.hoisted(() => ({
  pathname: "/stamboken/min-besattning",
  user: null as unknown,
}));
vi.mock("next/navigation", () => ({ usePathname: () => mocks.pathname }));
vi.mock("@/lib/user-context", () => ({ useOptionalUser: () => mocks.user }));

import {
  TOUR_STEPS,
  answerOffer,
  shouldOffer,
  stepsFor,
  visibleTarget,
} from "@/components/tour/tour";
import { TourContext, TourOffer } from "@/components/tour/Tour.client";

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

  it("names Matrikel in the role step for those who keep the register", () => {
    const roles = (user: UserContext) =>
      stepsFor(user, everywhere).find((s) => s.id === "roles")!;
    expect(roles(matrikelAdmin).text!(matrikelAdmin)).toBe(
      "roles.textMatrikel",
    );
    expect(roles(manager).text!(manager)).toBe("roles.textMatrikel");
    const viewer = { ...member, is_admin: true };
    expect(roles(viewer)).toBeDefined();
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
      const keys = [
        `${step.id}.title`,
        ...[member, matrikelAdmin].map(
          (u) => step.text?.(u) ?? `${step.id}.text`,
        ),
      ];
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

describe("TourOffer", () => {
  const start = vi.fn();
  const renderOffer = () =>
    render(
      <TourContext.Provider value={start}>
        <TourOffer />
      </TourContext.Provider>,
    );

  beforeEach(() => {
    localStorage.clear();
    start.mockClear();
    mocks.user = member;
    mocks.pathname = "/stamboken/min-besattning";
  });
  afterEach(cleanup);

  it("offers the tour on Min besättning and starts it only on yes", () => {
    renderOffer();
    expect(start).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Visa runt" }));
    expect(start).toHaveBeenCalledOnce();
    expect(
      screen.queryByRole("region", { name: "Rundtur i Stamboken" }),
    ).toBeNull();
  });

  it("does not ask again after Nej tack", () => {
    const { unmount } = renderOffer();
    fireEvent.click(screen.getByRole("button", { name: "Nej tack" }));
    expect(start).not.toHaveBeenCalled();
    unmount();
    renderOffer();
    expect(screen.queryByRole("button", { name: "Visa runt" })).toBeNull();
  });

  it("stays away from other pages, where the user is at work", () => {
    mocks.pathname = "/stamboken/arsrapport";
    renderOffer();
    expect(screen.queryByRole("button", { name: "Visa runt" })).toBeNull();
  });
});
