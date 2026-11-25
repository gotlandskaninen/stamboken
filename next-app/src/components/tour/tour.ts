import type { UserContext } from "@/lib/user-context";
import { MANUAL_PATH } from "@/lib/constants";
import { isMemberAdmin } from "@/app/(app)/stamboken/(dashboard)/admin/_components/navConfig";

export interface TourStep {
  /** i18n key under tour.steps, and the step's id in tests. */
  id: string;
  /** CSS selector; the first visible match is highlighted. */
  target: string;
  /** Where to point instead when the target hides after the tour started. */
  fallback?: string;
  /** Link into the manual or the matrikel guide; null: no link for this user. */
  href: string | ((user: UserContext) => string | null);
  /** The text's key under tour.steps when it depends on the user. */
  text?: (user: UserContext) => string;
  /** Only for users with this role; everyone when left out. */
  when?: (user: UserContext) => boolean;
}

/** A step as this user sees it, with its target on the page. */
export interface ShownStep {
  id: string;
  /** The selector looked up again each time the step is shown. */
  target: string;
  element: Element;
  href: string | null;
  textKey: string;
}

const GUIDE_PATH = "/medlem/guide";

// Same test as the matrikel page's canEdit and the guide's canReadGuide
// (guide.ts reads the disk, so it cannot be imported here).
const keepsMatrikel = (user: UserContext) =>
  user.is_admin || user.is_matrikel_admin;

// Adminpanelen differs per role: the admin's screens, the genbanksansvarig's
// screens, or for a matrikeladmin only the member register.
const adminHref = (user: UserContext) =>
  user.is_admin
    ? `${MANUAL_PATH}#adminpanel`
    : user.is_manager?.length
      ? `${MANUAL_PATH}#adminpanelen-för-genbanksansvarig`
      : `${GUIDE_PATH}#matrikeln`;

// The top nav hides on small screens; its links are then behind the menu button.
const nav = (key: string) => `[data-tour="nav-${key}"], [data-tour="menu"]`;

// Page steps first, then the menu around every page. The tour only points at
// what is on the current page, so it never navigates mid-tour.
export const TOUR_STEPS: TourStep[] = [
  {
    id: "tabs",
    target: '[role="tablist"]:has(#herd-tab-overview)',
    href: `${MANUAL_PATH}#min-besättning`,
  },
  {
    id: "kaniner",
    target: "#herd-tab-individuals",
    href: `${MANUAL_PATH}#kaninens-sida`,
  },
  {
    id: "kullar",
    target: "#herd-tab-breeding",
    href: `${MANUAL_PATH}#registrera-en-parning`,
  },
  {
    id: "kanin",
    target: '[data-tour="rabbit-card"]',
    href: `${MANUAL_PATH}#ladda-upp-ett-foto`,
  },
  {
    id: "adminPage",
    target: '[data-tour="admin-cards"]',
    href: adminHref,
    when: isMemberAdmin,
  },
  {
    id: "matrikelPage",
    target: '[data-tour="matrikel"]',
    // Those who only read the register cannot edit and get no guide (404).
    href: (user) => (keepsMatrikel(user) ? `${GUIDE_PATH}#matrikeln` : null),
    text: (user) =>
      keepsMatrikel(user) ? "matrikelPage.text" : "matrikelPage.textRead",
    when: isMemberAdmin,
  },
  {
    id: "arsrapport",
    target: nav("arsrapport"),
    href: `${MANUAL_PATH}#årsrapport`,
  },
  {
    id: "inkorg",
    // Only queue workers have the link, so the step needs it at the start
    // (on mobile it is skipped); if the window narrows later, the menu.
    target: '[data-tour="nav-inkorg"]',
    fallback: '[data-tour="menu"]',
    href: `${MANUAL_PATH}#arbeta-i-inkorgen`,
  },
  {
    id: "profil",
    target: nav("profil"),
    href: `${MANUAL_PATH}#uppdatera-din-profil`,
  },
  {
    id: "mode",
    target: '[data-tour="user-menu"]',
    href: `${MANUAL_PATH}#testmiljön-och-riktiga-stamboken`,
    // The switch is in the menu only for those with access to the real stamboken.
    when: (user) => user.v2_prod_access,
  },
  {
    id: "roles",
    target: '[data-tour="user-menu"]',
    href: adminHref,
    // Everyone who sees Adminpanelen in the menu (admin, genbanksansvarig,
    // matrikeladmin) also sees Matrikel there.
    when: isMemberAdmin,
  },
  {
    id: "tyckTill",
    target: '[data-tour="tyck-till"]',
    href: `${MANUAL_PATH}#tyck-till`,
  },
];

/** The first match that takes up space on screen, or null. */
export function visibleTarget(selector: string): Element | null {
  for (const el of document.querySelectorAll(selector)) {
    if (el.getClientRects().length > 0) return el;
  }
  return null;
}

/** The steps for this user whose target is on the page now. */
export function stepsFor(
  user: UserContext,
  find: (selector: string) => Element | null = visibleTarget,
): ShownStep[] {
  return TOUR_STEPS.flatMap((step) => {
    if (step.when && !step.when(user)) return [];
    const element = find(step.target);
    if (!element) return [];
    const href = typeof step.href === "function" ? step.href(user) : step.href;
    const textKey = step.text?.(user) ?? `${step.id}.text`;
    const target = step.fallback
      ? `${step.target}, ${step.fallback}`
      : step.target;
    return [{ id: step.id, target, element, href, textKey }];
  });
}

// The offer after the first login: shown on Min besättning until the user
// starts the tour or says no, per user and browser (no server-side store).
const offerKey = (userId: number) => `sb-tour-answered-${userId}`;

export function shouldOffer(userId: number): boolean {
  try {
    return localStorage.getItem(offerKey(userId)) !== "1";
  } catch {
    // Unavailable storage could not remember a no, so do not ask at all.
    return false;
  }
}

export function answerOffer(userId: number): void {
  try {
    localStorage.setItem(offerKey(userId), "1");
  } catch {
    // unavailable storage: shouldOffer already says no
  }
}
